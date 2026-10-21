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
import json
import os
import re
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from dotenv import load_dotenv
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

from server import call_bot, chat, clipdb, culture_filter, culturedb, feed, native_expr, people, phrase_gloss, pron, review, summary_jobs, tts, wordbook, youtube
from server.call_bot import parse_call_config, run_bot, time_limit_for_mode
from server import partner_memory
from server.history import list_calls, live_cost_of, load_call, totals as call_totals
from server.pricing import combine_cost
from server.readgloss import (
    LEMMA_RE,
    WORD_RE,
    bridge_lists,
    lookup_word,
    normalize_phrase,
    save_phrase,
    save_word,
    stored_phrase_keys,
    words_used,
)
from server.transcript_store import get_teachback_dir, get_transcript_dir, get_tutoring_dir
from server.lesson import (
    LessonError,
    get_lesson,
    lesson_text,
)
from server.learner_profile import ProfileError, load_profile, profile_brief, update_profile
from server.tutor import (
    GENERIC_TOPIC_WORDS,
    TutoringAnalysisError,
    latest_transcript_since,
    make_generate_text,
    normalize_clip_query,
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
app.include_router(phrase_gloss.router)
app.include_router(people.router)
app.include_router(review.router)
app.include_router(wordbook.router)
app.include_router(feed.router)

# Serve static files
# app.mount("/static", StaticFiles(directory="frontend"), name="static")

# Mount assets and other static directories from dist
if os.path.exists("dist/assets"):
    app.mount("/assets", StaticFiles(directory="dist/assets"), name="assets")
if os.path.exists("dist/audio-processors"):
    app.mount("/audio-processors", StaticFiles(directory="dist/audio-processors"), name="audio-processors")
@app.get("/api/status")
async def get_status():
    """화면이 통화 제한 시간(초)을 미리 알고 남은 시간을 보여 주는 데 쓴다. 친구 통화(smalltalk)는 제한이 없어 null이다."""
    return {
        "mode": "local",
        "time_limits": {
            "call": time_limit_for_mode("mission"),
            "teachback": time_limit_for_mode("teachback"),
            "smalltalk": time_limit_for_mode("smalltalk"),
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
    practice, wordbook_lists = await _bridge_lists_within(PRACTICE_DEADLINE_SEC)
    return {
        "load_failed": broken,
        "brief": "\n".join(part for part in (pron.pron_brief(pron_result), profile_brief(card)) if part),
        "pron": pron.weak_summary(pron_result),
        "interests": list(card["interests"]) if card else [],
        "updated": card["updated"] if card else None,
        "weak_points": [
            {"pattern": p["pattern"], "example": p["example"]} for p in (card["weak_points"][:3] if card else [])
        ],
        "next_goal": card["next_goal"] if card else "",
        "practice_words": practice,
        "wordbook": wordbook_lists,
        "native_expressions": await asyncio.to_thread(_native_hints, wordbook_lists),
    }


def _native_hints(wordbook_lists: dict) -> list:
    """친구 통화·채팅에 줄 원어민 표현 2개. 목록 파일이 없으면 빈 목록."""
    entries = native_expr.load()
    if not entries:
        return []
    saved = [str(p.get("text") or "") for p in wordbook_lists.get("phrases") or []]
    return native_expr.pick_for_friend(entries, saved, native_expr.recent_learner_text())


# 다리가 멈춰 있어도 홈 화면(기억 요약)이 오래 기다리지 않게 전체 시간을 자른다.
PRACTICE_DEADLINE_SEC = 3.0


async def _bridge_lists_within(seconds: float) -> tuple:
    """(통화에 써 볼 단어, 친구에게 보여 줄 단어장). 다리가 느리면 둘 다 빈 값."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(bridge_lists), timeout=seconds)
    except asyncio.TimeoutError:
        logger.info("readgloss practice words skipped: bridge too slow")
        return [], {"words": [], "phrases": []}


# 백그라운드 카드 갱신 작업. 참조를 안 잡으면 끝나기 전에 수거될 수 있다.
_background_tasks: "set[asyncio.Task]" = set()


def _update_profile_sync(tutoring: dict) -> bool:
    return update_profile(tutoring, generate_text=make_generate_text())


def _schedule_profile_update(tutoring: dict) -> None:
    """카드 갱신을 뒤에서 돌린다(검토가 끝난 뒤 review가 부른다). 실패해도 클라이언트에는 영향 없다."""

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


# 이미 학습자 카드 갱신을 걸어 둔 통화 전문 파일명.
_PROFILE_UPDATED: "set[str]" = set()


def _card_update_once(stem: str, tutoring: dict) -> None:
    """검토가 끝난 통화(또는 15분이 지난 통화)의 카드 갱신을 통화당 한 번만 건다."""
    name = f"{stem}.md"
    if name in _PROFILE_UPDATED:
        return
    _PROFILE_UPDATED.add(name)
    _schedule_profile_update(tutoring)


review.configure(_card_update_once)


def _spec_for(stem: str, body: Optional[dict]) -> summary_jobs.JobSpec:
    """통화 정리의 입력. 통화 때 서버가 남겨 둔 것이 먼저고, 없으면 화면이 보낸 본문으로 만든다(만들면 남겨 둔다)."""
    stored = summary_jobs.read_spec(stem)
    if stored is not None or body is None:
        return stored or summary_jobs.JobSpec()
    raw_practice = body.get("practice_words")
    lesson_date = body.get("lesson_date")
    spec = summary_jobs.JobSpec(
        mode="teachback" if body.get("mode") == "teachback" else "mission",
        lesson_date=lesson_date if isinstance(lesson_date, str) else None,
        practice_words=tuple(
            w for w in (raw_practice[:10] if isinstance(raw_practice, list) else []) if isinstance(w, str) and LEMMA_RE.fullmatch(w)
        ),
    )
    summary_jobs.write_spec(stem, spec)
    return spec


async def _complete_response(path: Path, spec: summary_jobs.JobSpec, data: dict, saved: bool) -> None:
    """분석 결과(또는 저장된 결과)에 화면 응답용 필드를 채운다."""
    data["saved"] = saved
    data["stem"] = path.stem
    if spec.mode != "teachback":
        data["practice_used"] = (
            words_used(path.read_text(encoding="utf-8"), list(spec.practice_words), _verbatim_text(path)) if spec.practice_words else []
        )
    # readgloss 단어장에는 자동으로 넣지 않는다. 사용자가 항목의 저장·별 버튼을 눌러야 들어간다(필드는 옛 클라이언트 호환으로 유지).
    data["readgloss"] = None
    data["cost"] = combine_cost(await asyncio.to_thread(live_cost_of, path), data.get("cost_usd"))


async def _stored_summary(path: Path, spec: summary_jobs.JobSpec) -> Optional[dict]:
    """이미 저장된 요약(서버가 재시작된 뒤 화면이 다시 부른 경우)을 응답 모양으로 돌려준다. 없으면 None. 모델은 부르지 않는다."""
    for directory in (get_teachback_dir(), get_tutoring_dir()):
        try:
            data = json.loads((directory / f"{path.stem}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data:
            kind = "teachback" if directory == get_teachback_dir() else spec.mode
            await _complete_response(path, summary_jobs.JobSpec(kind, spec.lesson_date, spec.practice_words), data, True)
            return data
    return None


async def _summary_job(path: Path, spec: summary_jobs.JobSpec) -> dict:
    """통화 한 건의 정리를 만든다. 통화 끝에 서버가 걸거나 /api/tutor가 부르며, 둘 다 summary_jobs가 통화당 하나만 돌린다."""
    stored = await _stored_summary(path, spec)
    if stored is not None:
        return stored
    if spec.mode == "teachback":
        # 숨은 노트(그날 수업 자료)를 불러와 teach-back 분석에 넘긴다.
        lesson = await asyncio.to_thread(get_lesson, spec.lesson_date)
        note_text = lesson_text(lesson)
        data, saved = await asyncio.to_thread(run_teachback, path, note_text, lesson.get("date"))
        await _complete_response(path, spec, data, saved)
        # 카드는 영어 교정만 반영한다. unanswered는 보안 지식 공백이라 제외. 갱신은 요약 검토가 끝난 뒤(review.finish) 또는 15분 뒤에 건다.
        skipped = ("saved", "stem", "lesson_date", "unanswered", "readgloss", "cost", "cost_usd")
    else:
        data, saved = await asyncio.to_thread(run_tutoring, path)
        await _complete_response(path, spec, data, saved)
        # 같은 통화를 다시 분석해도 카드는 한 번만 갱신한다(misses·count 중복 방지).
        skipped = ("saved", "stem", "practice_used", "readgloss", "cost", "cost_usd")
    if path.name not in _PROFILE_UPDATED:
        review.defer_card_update(path.stem, {k: v for k, v in data.items() if k not in skipped})
    return data


def _on_call_saved(saved: Path, config: call_bot.CallConfig) -> None:
    """통화 전문이 저장되면 서버가 스스로 정리를 건다. 화면이 닫혀 있어도 이어서 돈다."""
    path = Path(saved)
    spec = summary_jobs.JobSpec(mode=config.mode, lesson_date=config.lesson_date, practice_words=config.practice_words)
    summary_jobs.write_spec(path.stem, spec)
    summary_jobs.start(path.stem, lambda: _summary_job(path, spec))


call_bot.configure_call_saved(_on_call_saved)


def _verbatim_text(path: Path) -> str:
    """튜터링이 원음을 받아써 둔 글(없으면 빈 글)."""
    verbatim = get_tutoring_dir() / f"{path.stem}.verbatim.txt"
    return verbatim.read_text(encoding="utf-8") if verbatim.is_file() else ""


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


async def _save_request_latency(stem: str, latency: Any) -> None:
    """/api/tutor 본문에 실린 응답 속도를 저장한다. 없거나 형식이 틀려도 튜터 요청은 실패시키지 않는다."""
    if latency is None:
        return
    from server.history import save_latency

    try:
        if not isinstance(latency, dict):
            raise ValueError("latency는 객체여야 합니다")
        await asyncio.to_thread(save_latency, stem, latency)
    except (ValueError, FileNotFoundError) as e:
        logger.warning(f"latency not saved for {stem}: {e}")


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
    path = None

    def fail(status: int, detail: str):
        # 전문 경로가 정해진 뒤의 실패는 stem을 함께 알려 화면이 전문을 계속 보여 줄 수 있게 한다.
        if path is None:
            raise HTTPException(status_code=status, detail=detail)
        return JSONResponse({"detail": detail, "stem": path.stem}, status_code=status)

    try:
        path = await asyncio.to_thread(_wait_and_resolve_transcript, filename, started_at)
        # 전문 경로(stem)가 정해지면 분석 결과와 상관없이 응답 속도를 먼저 저장한다(분석 중 화면을 떠나도 남는다).
        await _save_request_latency(path.stem, body.get("latency"))

        spec = await asyncio.to_thread(_spec_for, path.stem, body)
        # 통화 끝에 서버가 건 작업이 있으면 거기에 합류하고, 없으면 지금 건다(통화당 하나, 모델을 두 번 부르지 않는다).
        data = await summary_jobs.wait(path.stem, lambda: _summary_job(path, spec))
    except LessonError as e:
        logger.error(f"Lesson fetch failed: {e}")
        return fail(e.status_code, str(e))
    except FileNotFoundError as e:
        return fail(404, str(e))
    except ValueError as e:
        return fail(400, str(e))
    except TutoringAnalysisError as e:
        logger.error(f"Tutoring failed: {e}")
        return fail(502, "튜터링 분석에 실패했습니다. 잠시 후 다시 시도해 주세요.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Tutoring failed: {e}")
        return fail(500, "Tutoring failed")

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
async def calls_endpoint(limit: int = 50, partner: Optional[str] = None):
    """저장된 통화 목록(최신순)과 누적 합계. partner=<id>면 그 사람의 통화만(park는 친구 표시가 없는 통화)."""
    limit = max(1, min(limit, 200))
    calls = await asyncio.to_thread(list_calls, limit, partner)
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


@app.post("/api/calls/{stem}/summary")
async def call_summary_endpoint(stem: str):
    """요약이 없거나 실패한 통화의 정리를 (다시) 시작한다. 이미 돌고 있거나 끝났으면 새로 걸지 않고 상태만 알려 준다."""
    from server.history import STEM_RE, has_summary

    if not STEM_RE.fullmatch(stem):
        raise HTTPException(status_code=400, detail="허용되지 않은 통화 번호입니다")
    path = get_transcript_dir() / f"{stem}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="해당 통화 기록이 없습니다")
    if await asyncio.to_thread(has_summary, stem):
        return {"summary": "done"}
    spec = await asyncio.to_thread(_spec_for, stem, None)
    summary_jobs.start(stem, lambda: _summary_job(path, spec))
    return {"summary": summary_jobs.unfinished_status(stem)}


@app.post("/api/calls/{stem}/latency")
async def call_latency_endpoint(stem: str, raw: Request):
    """클라이언트가 잰 응답 속도(turns_ms, first_audio_ms)를 통화 기록 옆에 저장한다. 형식이 틀리면 400, 통화가 없으면 404."""
    from server.history import save_latency

    body = await _json_object(raw)
    try:
        await asyncio.to_thread(save_latency, stem, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "ok"}


def _partner_or_400(partner_id: str) -> None:
    if not partner_memory.valid_partner(partner_id):
        raise HTTPException(status_code=400, detail="알 수 없는 친구입니다.")


@app.get("/api/partners/{partner_id}/memory")
async def partner_memory_get(partner_id: str):
    _partner_or_400(partner_id)
    try:
        memory = await asyncio.to_thread(partner_memory.load_memory, partner_id)
    except partner_memory.MemoryError_ as e:
        logger.error(f"Partner memory unreadable: {e}")
        raise HTTPException(status_code=500, detail="친구 기억을 읽지 못했습니다.")
    return {"status": "ok" if memory else "empty", "memory": memory}


@app.delete("/api/partners/{partner_id}/memory")
async def partner_memory_clear(partner_id: str):
    _partner_or_400(partner_id)
    await asyncio.to_thread(partner_memory.clear_memory, partner_id)
    return {"status": "ok"}


@app.delete("/api/partners/{partner_id}/memory/{kind}/{index}")
async def partner_memory_forget(partner_id: str, kind: str, index: int, text: Optional[str] = None):
    _partner_or_400(partner_id)
    if kind not in partner_memory.KINDS:
        raise HTTPException(status_code=400, detail="kind는 facts, threads, self_story, jokes, episodes 중 하나여야 합니다.")
    try:
        memory = await asyncio.to_thread(partner_memory.forget_item, partner_id, kind, index, None, text)
    except partner_memory.MemoryChanged:
        raise HTTPException(status_code=409, detail="기억이 바뀌었어요. 다시 불러와 주세요.")
    except IndexError:
        raise HTTPException(status_code=404, detail="해당 항목이 없습니다.")
    except partner_memory.MemoryError_ as e:
        logger.error(f"Partner memory unreadable: {e}")
        raise HTTPException(status_code=500, detail="친구 기억을 읽지 못했습니다.")
    return {"status": "ok", "memory": memory}


@app.get("/api/chat/{partner_id}")
async def chat_get(partner_id: str):
    """친구와 주고받은 문자 최근 200개. 여섯 친구가 아니면 400."""
    _partner_or_400(partner_id)
    messages = await asyncio.to_thread(chat.load_messages, partner_id)
    return {"messages": messages}


@app.post("/api/chat/{partner_id}")
async def chat_send(partner_id: str, raw: Request):
    """학습자 문자 하나를 보내고 친구의 답을 받는다. 답을 만들지 못하면 502(아무것도 저장하지 않는다)."""
    _partner_or_400(partner_id)
    body = await _json_object(raw)
    try:
        instruction, message = chat.check_request(body.get("instruction"), body.get("message"))
    except chat.ChatInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        return await asyncio.to_thread(chat.send, partner_id, instruction, message)
    except chat.ChatError:
        raise HTTPException(status_code=502, detail="답을 받지 못했어요. 잠시 뒤에 다시 보내 주세요.")


def _schedule_chat_memory_update(partner_id: str, turns: list, total: int) -> None:
    async def _run():
        nonlocal turns, total
        try:
            while await asyncio.to_thread(chat.finish_close, partner_id, turns, total):
                logger.info("Partner memory updated from chat: %s", partner_id)
                # 도는 동안 새 메시지가 쌓였으면(그 사이 close는 nothing이었다) 한 번 더 건다. 실패하면 멈춘다.
                nxt = await asyncio.to_thread(chat.prepare_close, partner_id)
                if nxt is None:
                    break
                turns, total = nxt
        except Exception as e:  # noqa: BLE001 - 기억 갱신은 부가 기능
            logger.error(f"Chat memory update failed: {e}")

    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@app.post("/api/chat/{partner_id}/close")
async def chat_close(partner_id: str, raw: Request):
    """대화를 떠날 때 부른다(JSON 본문 {} 필수). 아직 기억에 반영하지 않은 메시지가 있으면 친구 기억 갱신을 뒤에서 걸고 scheduled, 없으면 nothing."""
    _partner_or_400(partner_id)
    await _json_object(raw)
    prepared = await asyncio.to_thread(chat.prepare_close, partner_id)
    if prepared is None:
        return {"status": "nothing"}
    turns, total = prepared
    _schedule_chat_memory_update(partner_id, turns, total)
    return {"status": "scheduled"}


MAX_CLIPS = 5
DB_CLIPS_ENOUGH = 3


def _clip_phrases(tutoring: dict) -> list:
    """자막 DB에서 찾아볼 문구: 다음 목표 문구 → 짧은 교정(2~6낱말) → 단어장 단어(2자 이상)."""
    out: list = []

    def add(value) -> None:
        if isinstance(value, str):
            v = " ".join(value.split())
            if v and v.lower() not in {p.lower() for p in out}:
                out.append(v)

    retry = tutoring.get("retry")
    for p in (retry.get("target_phrases") if isinstance(retry, dict) else None) or []:
        add(p)
    for row in tutoring.get("corrections") or []:
        b = row.get("better") if isinstance(row, dict) else None
        if isinstance(b, str) and 2 <= len(b.split()) <= 6:
            add(b)
    for row in tutoring.get("vocab") or []:
        w = row.get("word") if isinstance(row, dict) else None
        if isinstance(w, str) and len(w.strip()) >= 2:
            add(w)
    return out


def _db_clips(tutoring: dict):
    """자막 DB에서 문구를 말하는 순간을 모은다. 영상은 겹치지 않게 최대 5개. (clips, 쓴 문구)."""
    clips: list = []
    used: list = []
    seen: set = set()
    if not clipdb.available():
        return clips, used
    phrases = _clip_phrases(tutoring)
    hits: dict = {}
    # 라운드 로빈: 모든 문구가 한 건씩 받은 뒤에야 둘째 건을 받는다.
    for _round in range(2):
        for phrase in phrases:
            if len(clips) >= MAX_CLIPS:
                break
            hit = None
            if phrase not in hits:
                hits[phrase] = list(clipdb.search(phrase, limit=2))
            while hits[phrase]:
                cand = hits[phrase].pop(0)
                vid = cand.get("video_id")
                if vid and vid not in seen:
                    hit = cand
                    break
            if hit is None:
                continue
            vid = hit["video_id"]
            seen.add(vid)
            if phrase not in used:
                used.append(phrase)
            clips.append(
                {
                    "id": vid,
                    "title": hit.get("title") or "",
                    "channel": hit.get("channel") or "",
                    "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                    "start": int(hit.get("start") or 0),
                    "text": hit.get("text") or "",
                    "phrase": phrase,
                    "source": "db",
                }
            )
    return clips, used


@app.get("/api/calls/{stem}/clips")
async def call_clips_endpoint(stem: str):
    """통화 주제 YouTube 클립. 키·검색어가 없거나 검색이 실패해도 200에 status로 알린다. stem이 틀리면 400, 없으면 404."""
    try:
        call = await asyncio.to_thread(load_call, stem)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    tutoring = call.get("tutoring") or {}
    raw_query = tutoring.get("clip_query")
    query = normalize_clip_query(raw_query)

    db_clips, phrases = await asyncio.to_thread(_db_clips, tutoring)
    if len(db_clips) >= DB_CLIPS_ENOUGH:
        return {"query": ", ".join(phrases), "clips": db_clips, "status": "ok", "source": "db"}

    if not query:
        if db_clips:
            return {"query": ", ".join(phrases), "clips": db_clips, "status": "ok", "source": "db"}
        return {"query": "", "clips": [], "status": "no_query"}
    try:
        found = await asyncio.to_thread(youtube.clips_for_call, stem, query)
    except youtube.YouTubeKeyMissing:
        if db_clips:
            return {"query": ", ".join(phrases), "clips": db_clips, "status": "ok", "source": "db"}
        return {"query": query, "clips": [], "status": "no_key"}
    except youtube.YouTubeError as e:
        logger.warning(f"clip search failed for {stem}: {type(e).__name__}: {e}")
        if db_clips:
            return {"query": ", ".join(phrases), "clips": db_clips, "status": "ok", "source": "db"}
        return {"query": query, "clips": [], "status": "error"}
    seen = {c["id"] for c in db_clips}
    clips = list(db_clips)
    for c in found:
        if len(clips) >= MAX_CLIPS:
            break
        if c.get("id") in seen:
            continue
        seen.add(c.get("id"))
        clips.append({**c, "source": "search"})
    return {"query": query, "clips": clips, "status": "ok", "source": "mixed" if db_clips else "search"}


MAX_CULTURE_TERMS = 6
MAX_CULTURE_FALLBACK_WORDS = 3
# 통화 주제와 맞는 것만 남기려고 DB에서 더 많이 가져온 뒤 culture_filter가 추린다.
CULTURE_CANDIDATE_BLEND = 12
CULTURE_CANDIDATE_BANK = 8


def _culture_terms(tutoring: dict) -> list:
    """문화 DB 검색어: topic_keywords(구절 그대로)를 먼저, 모자라면 clip_query·vocab·thinking_gaps 영어 단어를 최대 3개까지 채워 전체 6개 이하."""
    terms: list = []
    keywords = tutoring.get("topic_keywords")
    for kw in keywords if isinstance(keywords, list) else []:
        if not isinstance(kw, str):
            continue
        phrase = " ".join(re.sub(r"[^a-z ]", " ", kw.lower()).split())
        if phrase and phrase not in terms and not all(w in GENERIC_TOPIC_WORDS for w in phrase.split()):
            terms.append(phrase)
    texts = []
    if isinstance(tutoring.get("clip_query"), str):
        texts.append(tutoring["clip_query"])
    for item in tutoring.get("vocab") or []:
        if isinstance(item, dict) and isinstance(item.get("word"), str):
            texts.append(item["word"])
    for item in tutoring.get("thinking_gaps") or []:
        if isinstance(item, dict) and isinstance(item.get("english"), str):
            texts.append(item["english"])
    terms = terms[:MAX_CULTURE_TERMS]
    fallback = 0
    for text in texts:
        for w in re.findall(r"[A-Za-z]+", text):
            w = w.lower()
            if len(terms) >= MAX_CULTURE_TERMS or fallback >= MAX_CULTURE_FALLBACK_WORDS:
                return terms
            if len(w) >= 3 and w not in GENERIC_TOPIC_WORDS and not any(w in t.split() for t in terms):
                terms.append(w)
                fallback += 1
    return terms


@app.get("/api/calls/{stem}/culture")
async def call_culture_endpoint(stem: str):
    """통화 주제와 관련된 한·미 문화 차이(BLEnD)·규범(CultureBank). DB나 검색어가 없으면 200에 status로 알린다. stem이 틀리면 400, 없으면 404."""
    try:
        call = await asyncio.to_thread(load_call, stem)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    empty = {"terms": [], "blend": [], "bank": [], "attribution": culturedb.ATTRIBUTION}
    if not culturedb.available():
        return {**empty, "status": "no_db"}
    terms = _culture_terms(call.get("tutoring") or {})
    if not terms:
        return {**empty, "status": "no_terms"}
    found = await asyncio.to_thread(culturedb.search, terms, CULTURE_CANDIDATE_BLEND, CULTURE_CANDIDATE_BANK)
    found = culture_filter.filter_found(found, call.get("tutoring") or {})
    return {"status": "ok", "terms": terms, "blend": found["blend"], "bank": found["bank"], "attribution": culturedb.ATTRIBUTION}


ALLOWED_TTS_VOICES = frozenset({"Kore", "Leda", "Charon", "Iapetus", "Sulafat", "Fenrir", "Zephyr", "Achird"})


@app.post("/api/tts")
async def tts_endpoint(raw: Request):
    """파트너 문장을 Gemini 목소리로 읽은 WAV. JSON이 아니면 415, 문장·목소리가 틀리면 400, 모델이 실패하면 502."""
    body = await _json_object(raw)
    text, voice = body.get("text"), body.get("voice")
    if not isinstance(text, str) or not isinstance(voice, str):
        raise HTTPException(status_code=400, detail="text와 voice가 필요해요.")
    if voice not in ALLOWED_TTS_VOICES:
        raise HTTPException(status_code=400, detail="지원하지 않는 목소리예요.")
    try:
        tts.validate(text, voice)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        wav = await asyncio.to_thread(tts.synthesize, text, voice)
    except Exception as e:
        logger.warning(f"tts failed: {type(e).__name__}")
        raise HTTPException(status_code=502, detail="음성을 만들지 못했어요.")
    return Response(content=wav, media_type="audio/wav")


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


# 셸(index.html)·서비스 워커·매니페스트는 브라우저 HTTP 캐시가 옛 것을 주지 않게 매번 확인시킨다.
NO_CACHE_FILES = ("index.html", "sw.js", "manifest.webmanifest")
NO_CACHE_HEADERS = {"Cache-Control": "no-cache"}


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    dist_dir = os.path.realpath("dist")
    file_path = os.path.realpath(os.path.join(dist_dir, full_path))
    if full_path and file_path.startswith(dist_dir + os.sep) and os.path.isfile(file_path):
        if full_path in NO_CACHE_FILES:
            return FileResponse(file_path, headers=NO_CACHE_HEADERS)
        return FileResponse(file_path)

    return FileResponse("dist/index.html", headers=NO_CACHE_HEADERS)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8931))
    uvicorn.run(app, host="127.0.0.1", port=port)
