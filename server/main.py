# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import os
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional

from fastapi import BackgroundTasks, FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from dotenv import load_dotenv
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

from server import pron
from server.call_bot import parse_call_config, run_bot, smalltalk_time_limit_from_env
from server.history import list_calls, live_cost_of, load_call, totals as call_totals
from server.pricing import combine_cost
from server.readgloss import (
    LEMMA_RE,
    WORD_RE,
    lookup_word,
    normalize_phrase,
    practice_words,
    push_tutoring,
    save_phrase,
    save_word,
    stored_phrase_keys,
    words_used,
)
from server.transcript_store import get_tutoring_dir
from server.lesson import (
    LessonError,
    get_lesson,
    lesson_text,
    session_time_limit_from_env,
)
from server.learner_profile import ProfileError, load_profile, profile_brief, update_profile
from server.tutor import (
    TutoringAnalysisError,
    latest_transcript_since,
    make_generate_text,
    resolve_transcript,
    run_teachback,
    run_tutoring,
)


# Load environment variables
load_dotenv(override=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



# 통화 연결(WebRTC offer/answer)을 맡는 Pipecat 처리기. 서버가 꺼질 때 열린 연결을 닫는다.
_webrtc = SmallWebRTCRequestHandler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await _webrtc.close()


# CORS 미들웨어를 두지 않는다: 화면은 같은 출처에서만 부른다. 다른 웹 페이지가 이 서버로
# 유료 통화(/api/offer)를 열거나 수업 기록(/api/lesson)을 읽지 못하게 한다.
app = FastAPI(lifespan=lifespan)

# Serve static files
# app.mount("/static", StaticFiles(directory="frontend"), name="static")

# Mount assets and other static directories from dist
if os.path.exists("dist/assets"):
    app.mount("/assets", StaticFiles(directory="dist/assets"), name="assets")
if os.path.exists("dist/audio-processors"):
    app.mount("/audio-processors", StaticFiles(directory="dist/audio-processors"), name="audio-processors")
@app.get("/api/status")
async def get_status():
    """화면이 통화 제한 시간(초)을 미리 알고 남은 시간을 보여 주는 데 쓴다."""
    return {
        "mode": "local",
        "time_limits": {
            "call": session_time_limit_from_env(None),
            "teachback": session_time_limit_from_env("teachback"),
            "smalltalk": smalltalk_time_limit_from_env(),
        },
    }

@app.get("/api/learner-profile")
async def learner_profile_endpoint():
    """통화 시작 때 쓰는 학습자 카드 영어 요약. 카드가 없거나 깨졌으면 빈 요약(깨졌으면 load_failed)."""
    broken = False
    try:
        card = await asyncio.to_thread(load_profile)
    except ProfileError as e:
        logger.error(f"Learner profile unreadable: {e}")
        card = None
        broken = True
    pron_result = await asyncio.to_thread(pron.latest_result)
    return {
        "load_failed": broken,
        "brief": "\n".join(part for part in (profile_brief(card), pron.pron_brief(pron_result)) if part),
        "pron": pron.weak_summary(pron_result),
        "interests": list(card["interests"]) if card else [],
        "updated": card["updated"] if card else None,
        "weak_points": [
            {"pattern": p["pattern"], "example": p["example"]} for p in (card["weak_points"][:3] if card else [])
        ],
        "next_goal": card["next_goal"] if card else "",
        "practice_words": await _practice_words_within(PRACTICE_DEADLINE_SEC),
    }


# 다리가 멈춰 있어도 홈 화면(기억 요약)이 오래 기다리지 않게 전체 시간을 자른다.
PRACTICE_DEADLINE_SEC = 3.0


async def _practice_words_within(seconds: float) -> list:
    try:
        return await asyncio.wait_for(asyncio.to_thread(practice_words), timeout=seconds)
    except asyncio.TimeoutError:
        logger.info("readgloss practice words skipped: bridge too slow")
        return []


# 백그라운드 카드 갱신 작업. 참조를 안 잡으면 끝나기 전에 수거될 수 있다.
_background_tasks: "set[asyncio.Task]" = set()


def _update_profile_sync(tutoring: dict) -> bool:
    return update_profile(tutoring, generate_text=make_generate_text())


def _schedule_profile_update(tutoring: dict) -> None:
    """요약 응답을 늦추지 않도록 카드 갱신을 뒤에서 돌린다. 실패해도 클라이언트에는 영향 없다."""

    async def _run():
        try:
            if await asyncio.to_thread(_update_profile_sync, tutoring):
                logger.info("Learner profile updated")
        except Exception as e:
            logger.error(f"Learner profile update failed: {e}")

    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _wait_and_resolve_transcript(filename=None, started_at=None):
    """분석할 전사 파일을 정한다.

    클라이언트가 파일명을 보내면 sessions/ 안의 허용 패턴만 받는다(경로 주입 방지).
    started_at(epoch ms)이 있으면 그 시각 이후에 저장된 파일만 후보로 삼아 가장
    최신을 쓴다(어제 파일로 되돌아가는 폴백 없음). 저장이 아직 안 끝났을 수 있어
    최대 15초까지 0.5초 간격으로 다시 본다.
    """
    if filename:
        return resolve_transcript(filename)

    deadline = time.time() + 15.0
    while True:
        path = latest_transcript_since(started_at)
        if path is not None:
            return path
        if time.time() >= deadline:
            raise FileNotFoundError(
                "이번 통화의 전사 파일이 아직 없습니다. 통화가 너무 짧았을 수 있어요."
            )
        time.sleep(0.5)


# 같은 파일명(방금 통화)에 대한 중복 요청을 10초 안에 다시 받으면 저장된 결과를
# 그대로 돌려줘 Vertex 재호출을 막는다.
_TUTOR_CACHE: Dict[str, "tuple[float, dict]"] = {}
_TUTOR_CACHE_TTL_SEC = 10.0

# 이미 학습자 카드 갱신을 걸어 둔 통화 전문 파일명.
_PROFILE_UPDATED: "set[str]" = set()
# 이미 readgloss 단어장에 넣은 통화 전문 파일명.
_READGLOSS_PUSHED: "set[str]" = set()


def _verbatim_text(path: Path) -> str:
    """튜터링이 원음을 받아써 둔 글(없으면 빈 글)."""
    verbatim = get_tutoring_dir() / f"{path.stem}.verbatim.txt"
    return verbatim.read_text(encoding="utf-8") if verbatim.is_file() else ""


async def _push_to_readgloss(path: Path, tutoring: dict) -> Optional[dict]:
    """통화당 한 번 튜터링의 새 단어·고친 표현을 readgloss 단어장에 넣는다. 다리가 꺼져 있으면 None(다음 요청 때 다시 시도)."""
    if path.name in _READGLOSS_PUSHED:
        return None
    _READGLOSS_PUSHED.add(path.name)
    saved = await asyncio.to_thread(push_tutoring, tutoring, f"English Tutor 통화 {path.stem[:10]}")
    if saved is None:
        _READGLOSS_PUSHED.discard(path.name)
        return None
    return {"saved": saved}


@app.get("/api/lesson")
async def lesson_endpoint(request: Request, date: Optional[str] = None):
    """그날의 수업 자료(걸러낸 절 목록)를 돌려준다. date 생략 시 가장 최근 기록.

    거르기는 작업실 코드를 하위 프로세스(scripts/lesson_dump.py)로 재사용한다.
    차단어 목록이 없거나 깨졌으면 500, 기록이 없으면 404, 날짜 형식이 틀리면 400.
    """
    try:
        data = await asyncio.to_thread(get_lesson, date)
    except LessonError as e:
        logger.error(f"Lesson fetch failed: {e}")
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return JSONResponse(data)


@app.post("/api/tutor")
async def tutor_endpoint(request: Request):
    """방금 저장된 통화 전문을 분석해 튜터링 JSON을 돌려준다.

    클라이언트는 임의 경로를 보낼 수 없다. 파일명을 보내더라도 sessions/ 안의
    `YYYY-MM-DD-HHMMSS.md` 패턴만 허용하고, 시작 시각(started_at, epoch ms)이
    있으면 그 이후에 저장된 파일만 쓴다.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    filename = body.get("filename")
    started_at = body.get("started_at")
    mode = body.get("mode")
    lesson_date = body.get("lesson_date")
    raw_practice = body.get("practice_words")
    practice = [
        w for w in (raw_practice[:10] if isinstance(raw_practice, list) else []) if isinstance(w, str) and LEMMA_RE.fullmatch(w)
    ]

    try:
        path = await asyncio.to_thread(_wait_and_resolve_transcript, filename, started_at)

        if mode == "teachback":
            # 숨은 노트(그날 수업 자료)를 불러와 teach-back 분석에 넘긴다.
            lesson = await asyncio.to_thread(get_lesson, lesson_date)
            note_text = lesson_text(lesson)
            resolved_date = lesson.get("date")
            cache_key = f"teachback:{path.name}:{resolved_date}"
            cached = _TUTOR_CACHE.get(cache_key)
            if cached and time.time() - cached[0] < _TUTOR_CACHE_TTL_SEC:
                return JSONResponse(cached[1])

            data, saved = await asyncio.to_thread(
                run_teachback, path, note_text, resolved_date
            )
            data["saved"] = saved
            data["readgloss"] = await _push_to_readgloss(path, data)
            data["cost"] = combine_cost(await asyncio.to_thread(live_cost_of, path), data.get("cost_usd"))
            _TUTOR_CACHE[cache_key] = (time.time(), data)
            # 카드는 영어 교정만 반영한다. unanswered는 보안 지식 공백이라 제외.
            if path.name not in _PROFILE_UPDATED:
                _PROFILE_UPDATED.add(path.name)
                _schedule_profile_update(
                    {k: v for k, v in data.items() if k not in ("saved", "lesson_date", "unanswered", "readgloss", "cost", "cost_usd")}
                )
            return JSONResponse(data)

        cached = _TUTOR_CACHE.get(path.name)
        if cached and time.time() - cached[0] < _TUTOR_CACHE_TTL_SEC:
            return JSONResponse(cached[1])

        data, saved = await asyncio.to_thread(run_tutoring, path)
        data["saved"] = saved
        data["practice_used"] = (
            words_used(path.read_text(encoding="utf-8"), practice, _verbatim_text(path)) if practice else []
        )
        data["readgloss"] = await _push_to_readgloss(path, data)
        data["cost"] = combine_cost(await asyncio.to_thread(live_cost_of, path), data.get("cost_usd"))
        _TUTOR_CACHE[path.name] = (time.time(), data)
        # 같은 통화를 다시 분석해도 카드는 한 번만 갱신한다(misses·count 중복 방지).
        if path.name not in _PROFILE_UPDATED:
            _PROFILE_UPDATED.add(path.name)
            _schedule_profile_update(
                {k: v for k, v in data.items() if k not in ("saved", "practice_used", "readgloss", "cost", "cost_usd")}
            )
    except LessonError as e:
        logger.error(f"Lesson fetch failed: {e}")
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TutoringAnalysisError as e:
        logger.error(f"Tutoring failed: {e}")
        raise HTTPException(
            status_code=502,
            detail="튜터링 분석에 실패했습니다. 잠시 후 다시 시도해 주세요.",
        )
    except Exception as e:
        logger.error(f"Tutoring failed: {e}")
        raise HTTPException(status_code=500, detail="Tutoring failed")

    return JSONResponse(data)

@app.post("/api/offer")
async def offer(raw: Request, background_tasks: BackgroundTasks):
    """브라우저의 WebRTC offer를 받아 answer를 돌려주고, 새 연결이면 통화 봇을 띄운다.

    브라우저 SDK는 통화 설정을 `requestData`(camelCase)로 보낸다. FastAPI 자동 해석은 이 이름을
    못 읽으므로 본문을 직접 읽어 Pipecat의 `from_dict`(두 이름 모두 허용)로 만든다.
    """
    if "application/json" not in raw.headers.get("content-type", ""):
        # 다른 페이지의 단순 요청(text/plain 등)은 사전 확인 없이 올 수 있어 JSON만 받는다.
        raise HTTPException(status_code=415, detail="WebRTC offer는 JSON으로 보내야 합니다.")
    try:
        body = await raw.json()
        request = SmallWebRTCRequest.from_dict(body)
    except Exception:
        raise HTTPException(status_code=400, detail="WebRTC offer 형식이 아닙니다.")
    try:
        config = parse_call_config(request.request_data) if not request.pc_id else None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    async def on_new_connection(connection):
        background_tasks.add_task(run_bot, connection, config or parse_call_config(request.request_data))

    answer = await _webrtc.handle_web_request(request=request, webrtc_connection_callback=on_new_connection)
    if answer is None:
        raise HTTPException(status_code=500, detail="WebRTC 연결을 만들지 못했습니다.")
    return answer


@app.patch("/api/offer")
async def ice_candidate(request: SmallWebRTCPatchRequest):
    try:
        await _webrtc.handle_patch_request(request)
    except (AssertionError, ValueError, IndexError) as e:
        logger.info(f"ICE candidate rejected: {e!r}")
        # 모르는 pc_id는 pipecat이 이미 404를 준다. 형식이 틀린 ICE 후보는 aiortc candidate_from_sdp가 이 예외들을 내서 500이 됐다.
        raise HTTPException(status_code=400, detail="ICE 후보 형식이 틀렸습니다.") from e
    return {"status": "success"}


@app.get("/api/calls")
async def calls_endpoint(limit: int = 50):
    """저장된 통화 목록(최신순)과 누적 합계. 화면의 통화 기록과 홈 합계가 쓴다."""
    limit = max(1, min(limit, 200))
    calls = await asyncio.to_thread(list_calls, limit)
    return {"totals": await asyncio.to_thread(call_totals), "calls": calls}


@app.get("/api/calls/{stem}")
async def call_detail_endpoint(stem: str):
    """통화 한 건과 저장된 튜터링(없으면 null). stem 형식이 틀리면 400, 없으면 404."""
    try:
        return await asyncio.to_thread(load_call, stem)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


READGLOSS_OFF_DETAIL = "readgloss가 꺼져 있어 뜻을 찾지 못했어요."
READGLOSS_SAVE_OFF_DETAIL = "readgloss가 꺼져 있어 단어를 저장하지 못했어요."
MAX_SENTENCE_CHARS = 1000
MAX_GLOSS_CHARS = 200


async def _json_object(raw: Request) -> dict:
    """JSON 객체 본문만 받는다. 다른 페이지의 단순 요청(text/plain 등)은 415, 형식이 틀리면 400."""
    if "application/json" not in raw.headers.get("content-type", ""):
        raise HTTPException(status_code=415, detail="JSON으로 보내야 합니다.")
    try:
        body = await raw.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="요청 형식이 틀렸어요.")
    return body


def _english_word(value) -> str:
    word = value.strip() if isinstance(value, str) else ""
    if not WORD_RE.fullmatch(word):
        raise HTTPException(status_code=400, detail="영어 단어 하나만 찾을 수 있어요.")
    return word


@app.post("/api/word")
async def word_endpoint(raw: Request):
    """readgloss 사전에서 영어 단어 하나의 뜻을 찾는다. 다리가 꺼져 있으면 503."""
    word = _english_word((await _json_object(raw)).get("word"))
    result = await asyncio.to_thread(lookup_word, word)
    if result is None:
        raise HTTPException(status_code=503, detail=READGLOSS_OFF_DETAIL)
    return result


@app.post("/api/word/save")
async def word_save_endpoint(raw: Request):
    """찾은 단어를 readgloss 단어장에 저장한다. 다리가 꺼져 있으면 503."""
    body = await _json_object(raw)
    word = _english_word(body.get("word"))
    lemma = body.get("lemma")
    gloss = body.get("gloss", "")
    sentence = body.get("sentence", "")
    if not isinstance(lemma, str) or not LEMMA_RE.fullmatch(lemma.strip().lower()):
        raise HTTPException(status_code=400, detail="원형 형식이 틀렸어요.")
    if not isinstance(gloss, str) or len(gloss) > MAX_GLOSS_CHARS:
        raise HTTPException(status_code=400, detail="뜻은 문자열 200자 이하여야 해요.")
    if not isinstance(sentence, str) or len(sentence) > MAX_SENTENCE_CHARS:
        raise HTTPException(status_code=400, detail="문장은 문자열 1000자 이하여야 해요.")
    saved = await asyncio.to_thread(save_word, lemma.strip().lower(), word, gloss, sentence)
    if not saved:
        raise HTTPException(status_code=503, detail=READGLOSS_SAVE_OFF_DETAIL)
    return {"saved": True}


READGLOSS_PHRASE_OFF_DETAIL = "readgloss가 꺼져 있어 저장하지 못했어요."
READGLOSS_STATUS_OFF_DETAIL = "readgloss가 꺼져 있어 저장 여부를 확인하지 못했어요."
MAX_TRANSLATION_CHARS = 300
MAX_STATUS_TEXTS = 40


@app.post("/api/phrase/save")
async def phrase_save_endpoint(raw: Request):
    """문장 하나를 readgloss 구 카드로 저장한다. 다리가 꺼져 있으면 503."""
    body = await _json_object(raw)
    text = body.get("text")
    text = " ".join(text.split()) if isinstance(text, str) else ""
    translation = body.get("translation", "")
    if not 2 <= len(text) <= MAX_SENTENCE_CHARS or not any(ch.isalpha() for ch in text):
        raise HTTPException(status_code=400, detail="문장은 글자가 있는 2자 이상 1000자 이하여야 해요.")
    if not isinstance(translation, str) or len(translation) > MAX_TRANSLATION_CHARS:
        raise HTTPException(status_code=400, detail="번역은 문자열 300자 이하여야 해요.")
    if not await asyncio.to_thread(save_phrase, text, translation.strip()):
        raise HTTPException(status_code=503, detail=READGLOSS_PHRASE_OFF_DETAIL)
    return {"saved": True}


@app.post("/api/phrase/status")
async def phrase_status_endpoint(raw: Request):
    """문장들이 이미 readgloss에 저장돼 있는지(공백·대소문자를 무시하고) 순서대로 답한다. 다리가 꺼져 있으면 503."""
    texts = (await _json_object(raw)).get("texts")
    if not isinstance(texts, list) or len(texts) > MAX_STATUS_TEXTS or not all(isinstance(t, str) for t in texts):
        raise HTTPException(status_code=400, detail="texts는 문자열 40개 이하의 배열이어야 해요.")
    keys = await asyncio.to_thread(stored_phrase_keys)
    if keys is None:
        raise HTTPException(status_code=503, detail=READGLOSS_STATUS_OFF_DETAIL)
    return {"saved": [normalize_phrase(t) in keys for t in texts]}


WAV_CONTENT_TYPES = ("audio/wav", "audio/x-wav", "audio/wave")
PRON_FAILED_DETAIL = "발음을 받아쓰지 못했어요. 잠시 후 다시 해 주세요."


@app.get("/api/pron/test")
async def pron_test_endpoint():
    """발음 시험 문항(섞인 순서, id와 문장만). 정답(target·other)은 보내지 않는다."""
    return pron.build_test()


@app.post("/api/pron/transcribe")
async def pron_transcribe_endpoint(raw: Request):
    """문장 하나를 읽은 WAV(2MB 이하)를 정답을 모른 채 받아쓴다. 모델 실패는 502."""
    content_type = raw.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in WAV_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="WAV 오디오로 보내야 해요.")
    too_big = HTTPException(status_code=413, detail="오디오가 2MB를 넘어요.")
    declared = raw.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > pron.MAX_WAV_BYTES:
        raise too_big
    data = bytearray()
    async for chunk in raw.stream():
        data.extend(chunk)
        if len(data) > pron.MAX_WAV_BYTES:
            raise too_big
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise HTTPException(status_code=400, detail="WAV 파일이 아니에요.")
    try:
        text = await asyncio.to_thread(pron.transcribe_wav, bytes(data))
    except Exception as e:
        logger.error(f"Pronunciation transcription failed: {e}")
        raise HTTPException(status_code=502, detail=PRON_FAILED_DETAIL)
    return {"text": text}


@app.post("/api/pron/finish")
async def pron_finish_endpoint(raw: Request):
    """받아쓴 답을 판정·집계해 PRON_DIR에 저장하고 결과를 돌려준다."""
    try:
        answers = pron.validate_answers(await _json_object(raw))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await asyncio.to_thread(pron.finish, answers)


@app.get("/api/pron/latest")
async def pron_latest_endpoint():
    """가장 최근 시험 결과 그대로. 없으면 {"result": null}."""
    return await asyncio.to_thread(pron.latest_result) or {"result": None}


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    dist_dir = os.path.realpath("dist")
    file_path = os.path.realpath(os.path.join(dist_dir, full_path))
    if full_path and file_path.startswith(dist_dir + os.sep) and os.path.isfile(file_path):
        return FileResponse(file_path)

    return FileResponse("dist/index.html")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8931))
    uvicorn.run(app, host="127.0.0.1", port=port)
