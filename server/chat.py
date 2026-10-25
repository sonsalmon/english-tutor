"""여섯 친구와의 문자 채팅.

CHAT_DIR/<id>.jsonl 에 메시지를 한 줄씩 덧붙이고(role me|friend, text, at), CHAT_DIR/<id>.state.json 에
"친구 기억에 이미 반영한 메시지 수"를 둔다. 답은 Vertex 텍스트 모델(tutor와 같은 클라이언트·모델)이 만들고,
시스템 지시문은 화면이 보낸다(buildChatInstruction). 대화를 떠날 때 close가 아직 반영하지 않은 메시지만으로
partner_memory.update(mode="chat")를 돌린다.
"""

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from server import partner_memory

logger = logging.getLogger(__name__)

CHAT_DIR_ENV = "CHAT_DIR"
DEFAULT_CHAT_DIR = "~/dev/learning/english/chats"

MAX_INSTRUCTION = 24000
MAX_MESSAGE = 1000
MAX_REPLY = 1500
SHOWN_MESSAGES = 200  # GET이 돌려주는 개수
MODEL_MESSAGES = 30  # 모델에 보내는 대화 길이
MEMORY_MESSAGES = 60  # 한 번의 기억 갱신에 쓰는 최대 메시지 수(가장 최근 것)
ROLES = ("me", "friend")


class ChatError(Exception):
    """모델이 답을 주지 못했을 때."""


class ChatInputError(ValueError):
    """요청 값이 규칙을 어길 때(메시지는 화면에 그대로 보여 줘도 되는 한국어)."""


_FILE_LOCK = threading.RLock()
_PARTNER_LOCKS: Dict[str, threading.Lock] = {}
_INFLIGHT: Dict[str, int] = {}  # 친구별로 지금 기억 갱신 중인 메시지 수(친구당 갱신은 한 번에 하나만 돈다)
REPLY_TIMEOUT_MS = 30_000  # 채팅 답 요청 시간 제한(멈춘 Vertex가 친구 락을 계속 잡지 않게)
_CLIENT: Any = None


def get_chat_dir() -> Path:
    return Path(os.path.expanduser(os.getenv(CHAT_DIR_ENV) or DEFAULT_CHAT_DIR))


def valid_partner(partner_id: Any) -> bool:
    return partner_memory.valid_partner(partner_id)


def chat_path(partner_id: str) -> Path:
    if not valid_partner(partner_id):
        raise ValueError(f"알 수 없는 친구: {partner_id!r}")
    return get_chat_dir() / f"{partner_id}.jsonl"


def state_path(partner_id: str) -> Path:
    if not valid_partner(partner_id):
        raise ValueError(f"알 수 없는 친구: {partner_id!r}")
    return get_chat_dir() / f"{partner_id}.state.json"


def marks_path(partner_id: str) -> Path:
    if not valid_partner(partner_id):
        raise ValueError(f"알 수 없는 친구: {partner_id!r}")
    return get_chat_dir() / f"{partner_id}.marks.json"


def message_id(m: Dict[str, str]) -> str:
    """메시지 파일을 고치지 않고도 정해지는 고정 id(역할·시각·글에서 만든다)."""
    return hashlib.sha1(f"{m['role']}|{m['at']}|{m['text']}".encode("utf-8")).hexdigest()[:12]


def partner_lock(partner_id: str) -> threading.Lock:
    with _FILE_LOCK:
        return _PARTNER_LOCKS.setdefault(partner_id, threading.Lock())


def _now() -> str:
    return datetime.now(partner_memory.KST).isoformat(timespec="seconds")


def check_request(instruction: Any, message: Any) -> Tuple[str, str]:
    """요청 본문의 instruction·message를 검사하고 (instruction, message)를 돌려준다."""
    if not isinstance(instruction, str) or not instruction.strip():
        raise ChatInputError("instruction이 필요해요.")
    if len(instruction) > MAX_INSTRUCTION:
        raise ChatInputError("instruction이 너무 길어요.")
    if not isinstance(message, str) or not message.strip():
        raise ChatInputError("메시지를 입력해 주세요.")
    message = message.strip()
    if len(message) > MAX_MESSAGE:
        raise ChatInputError(f"메시지는 {MAX_MESSAGE}자까지 보낼 수 있어요.")
    return instruction, message


def read_all(partner_id: str) -> List[Dict[str, str]]:
    """파일의 모든 메시지. 깨진 줄은 건너뛴다."""
    path = chat_path(partner_id)
    with _FILE_LOCK:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
    messages: List[Dict[str, str]] = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(item, dict)
            and item.get("role") in ROLES
            and isinstance(item.get("text"), str)
            and item["text"].strip()
        ):
            messages.append({"role": item["role"], "text": item["text"], "at": str(item.get("at") or "")})
    return messages


def read_marks(partner_id: str) -> Dict[str, List[str]]:
    """{'pinned': [...], 'deleted': [...]}. 파일이 없거나 깨졌으면 둘 다 비어 있다."""
    try:
        data = json.loads(marks_path(partner_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        data = {}
    out: Dict[str, List[str]] = {}
    for key in ("pinned", "deleted"):
        items = data.get(key) if isinstance(data, dict) else None
        out[key] = [i for i in items if isinstance(i, str)] if isinstance(items, list) else []
    return out


def _write_marks(partner_id: str, marks: Dict[str, List[str]]) -> None:
    path = marks_path(partner_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".marks-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(marks, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_visible(partner_id: str) -> List[Dict[str, Any]]:
    """지워지지 않은 모든 메시지(id·pinned 포함). 화면과 모델 문맥은 이 목록만 쓴다."""
    with _FILE_LOCK:
        messages = read_all(partner_id)
        marks = read_marks(partner_id)
    deleted, pinned = set(marks["deleted"]), set(marks["pinned"])
    out: List[Dict[str, Any]] = []
    for m in messages:
        mid = message_id(m)
        if mid not in deleted:
            out.append({**m, "id": mid, "pinned": mid in pinned})
    return out


def load_messages(partner_id: str, limit: int = SHOWN_MESSAGES) -> List[Dict[str, str]]:
    """지워진 메시지를 뺀 최근 메시지(role·text·at)."""
    return [{k: m[k] for k in ("role", "text", "at")} for m in read_visible(partner_id)[-limit:]]


def load_view(partner_id: str, limit: int = SHOWN_MESSAGES) -> Dict[str, Any]:
    """화면용: 최근 메시지(id·pinned 포함)와, 오래되어 목록 밖이어도 보여 줄 고정 메시지 전부."""
    visible = read_visible(partner_id)
    return {"messages": visible[-limit:], "pinned": [m for m in visible if m["pinned"]]}


def _toggle(partner_id: str, mid: str, update: Callable[[Dict[str, List[str]]], None]) -> None:
    with _FILE_LOCK:
        if not any(m["id"] == mid for m in read_visible(partner_id)):
            raise KeyError(mid)
        marks = read_marks(partner_id)
        update(marks)
        _write_marks(partner_id, marks)


def set_pinned(partner_id: str, mid: str, pinned: bool) -> None:
    """메시지를 고정하거나 고정을 푼다. 없는(또는 지워진) 메시지면 KeyError."""

    def update(marks: Dict[str, List[str]]) -> None:
        keep = [i for i in marks["pinned"] if i != mid]
        marks["pinned"] = keep + [mid] if pinned else keep

    _toggle(partner_id, mid, update)


def delete_message(partner_id: str, mid: str) -> None:
    """메시지를 지운 것으로 표시한다(파일의 줄은 그대로 두어 기억 반영 위치가 어긋나지 않는다). 없으면 KeyError."""

    def update(marks: Dict[str, List[str]]) -> None:
        marks["pinned"] = [i for i in marks["pinned"] if i != mid]
        if mid not in marks["deleted"]:
            marks["deleted"].append(mid)

    _toggle(partner_id, mid, update)


def append_messages(partner_id: str, messages: List[Dict[str, str]]) -> None:
    path = chat_path(partner_id)
    lines = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages)
    with _FILE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab+") as probe:  # 지난번에 덧붙이다 죽어 마지막 줄이 반쯤 쓰였으면 줄바꿈부터 쓴다
            size = probe.seek(0, os.SEEK_END)
            if size:
                probe.seek(size - 1)
                needs_newline = probe.read(1) != b"\n"
            else:
                needs_newline = False
        with open(path, "a", encoding="utf-8") as f:
            if needs_newline:
                f.write("\n")
            f.write(lines)
            f.flush()
            os.fsync(f.fileno())


_MD_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)]|#{1,6})\s+", re.MULTILINE)


def clean_reply(raw: Any) -> str:
    """모델 답에서 마크다운 기호를 걷어 메시지 앱 글처럼 만든다. 빈 답은 ChatError."""
    if not isinstance(raw, str):
        raise ChatError("빈 답")
    text = raw.replace("```", "")
    text = _MD_BULLET.sub("", text)
    text = re.sub(r"\*\*|__|`", "", text)
    text = re.sub(r"(?<![\w*])\*(?=\S)|(?<=\S)\*(?![\w*])", "", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    if len(text) > MAX_REPLY:
        text = text[:MAX_REPLY].rsplit(" ", 1)[0].rstrip(" ,;:-")
    if not text:
        raise ChatError("빈 답")
    return text


def contents_for(messages: List[Dict[str, str]]) -> List[Tuple[str, str]]:
    """최근 메시지를 모델용 (role, text)로 만든다. 모델은 user로 시작해야 하므로 앞쪽 friend는 버리고, 같은 role이 이어지면 합친다."""
    window = messages[-MODEL_MESSAGES:]
    while window and window[0]["role"] != "me":
        window = window[1:]
    out: List[Tuple[str, str]] = []
    for m in window:
        role = "user" if m["role"] == "me" else "model"
        if out and out[-1][0] == role:
            out[-1] = (role, out[-1][1] + "\n" + m["text"])
        else:
            out.append((role, m["text"]))
    return out


def _get_client() -> Any:
    """채팅 답용 클라이언트를 한 번만 만들어 재사용한다(요청 시간 제한 포함)."""
    global _CLIENT
    from google.genai import types

    from server import tutor

    with _FILE_LOCK:
        if _CLIENT is None:
            _CLIENT = tutor._make_client(http_options=types.HttpOptions(timeout=REPLY_TIMEOUT_MS))
        return _CLIENT


def generate_reply(instruction: str, history: List[Dict[str, str]]) -> str:
    """Vertex 텍스트 모델로 친구의 답을 만든다(마크다운 정리 전의 원문)."""
    from google.genai import types

    from server import tutor

    model = tutor.tutor_model()
    client = _get_client()
    contents = [types.Content(role=role, parts=[types.Part(text=text)]) for role, text in contents_for(history)]
    config = types.GenerateContentConfig(
        system_instruction=instruction,
        thinking_config=types.ThinkingConfig(thinking_budget=0) if "flash" in model else None,
    )
    response = client.models.generate_content(model=model, contents=contents, config=config)
    tutor.record_usage(response)
    return response.text


def send(
    partner_id: str,
    instruction: str,
    message: str,
    generate: Optional[Callable[[str, List[Dict[str, str]]], str]] = None,
) -> Dict[str, Any]:
    """학습자 메시지를 받아 친구의 답을 만들고 둘 다 파일에 덧붙인다. 답을 못 받으면 아무것도 쓰지 않고 ChatError."""
    generate = generate or generate_reply
    with partner_lock(partner_id):
        history = [{k: m[k] for k in ('role', 'text', 'at')} for m in read_visible(partner_id)]
        mine = {"role": "me", "text": message, "at": _now()}
        try:
            reply = clean_reply(generate(instruction, history + [mine]))
        except ChatError:
            raise
        except Exception as e:  # noqa: BLE001 - 모델·네트워크 오류는 화면에 한 가지 문구로
            logger.warning("chat reply failed (%s): %s", partner_id, type(e).__name__)
            raise ChatError(str(type(e).__name__)) from e
        theirs = {"role": "friend", "text": reply, "at": _now()}
        append_messages(partner_id, [mine, theirs])
    shown = [{**m, "id": message_id(m), "pinned": False} for m in (mine, theirs)]
    return {"reply": reply, "messages": shown}


def _read_state(partner_id: str) -> int:
    try:
        data = json.loads(state_path(partner_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return 0
    count = data.get("memorized") if isinstance(data, dict) else 0
    return count if isinstance(count, int) and count >= 0 else 0


def _write_state(partner_id: str, memorized: int) -> None:
    path = state_path(partner_id)
    with _FILE_LOCK:
        memorized = max(memorized, _read_state(partner_id))  # 반영한 수는 뒤로 가지 않는다
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"memorized": memorized, "updated": _now()}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def prepare_close(partner_id: str) -> Optional[Tuple[List[Tuple[str, str]], int]]:
    """아직 기억에 반영하지 않은 메시지로 (턴, 전체 메시지 수)를 만든다. 학습자 메시지가 없거나 이 친구의 갱신이 이미 진행 중이면 None."""
    with _FILE_LOCK:
        messages = read_all(partner_id)
        total = len(messages)
        deleted = set(read_marks(partner_id)["deleted"])
        pending = [m for m in messages[min(_read_state(partner_id), total) :] if message_id(m) not in deleted]
        if not any(m["role"] == "me" for m in pending):
            return None
        if partner_id in _INFLIGHT:  # 진행 중이면 겹쳐 돌리지 않는다. 끝난 뒤 남은 메시지는 호출한 쪽이 한 번 더 건다.
            return None
        _INFLIGHT[partner_id] = total
    turns = [(m["role"] if m["role"] == "me" else "partner", m["text"]) for m in pending[-MEMORY_MESSAGES:]]
    return turns, total


def finish_close(
    partner_id: str,
    turns: List[Tuple[str, str]],
    total: int,
    generate_text: Optional[Callable[[str], Any]] = None,
) -> bool:
    """prepare_close가 만든 턴으로 친구 기억을 갱신한다. 성공하면 반영한 수를 저장하고 True."""
    try:
        if generate_text is None:
            from server.tutor import make_generate_text

            generate_text = make_generate_text()
        ok = partner_memory.update(partner_id, turns, generate_text=generate_text, mode="chat")
        if ok:
            _write_state(partner_id, total)
        return ok
    finally:
        with _FILE_LOCK:
            _INFLIGHT.pop(partner_id, None)
