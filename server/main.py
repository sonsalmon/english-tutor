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
from typing import Dict, Optional

from fastapi import BackgroundTasks, FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

from server.call_bot import parse_call_config, run_bot
from server.lesson import (
    LessonError,
    get_lesson,
    lesson_text,
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


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
# app.mount("/static", StaticFiles(directory="frontend"), name="static")

# Mount assets and other static directories from dist
if os.path.exists("dist/assets"):
    app.mount("/assets", StaticFiles(directory="dist/assets"), name="assets")
if os.path.exists("dist/audio-processors"):
    app.mount("/audio-processors", StaticFiles(directory="dist/audio-processors"), name="audio-processors")
@app.get("/api/status")
async def get_status():
    """혼자 쓰는 로컬 앱이라 배포용 설정(reCAPTCHA·Redis)이 없다. 화면 경고를 띄우지 않는다."""
    return {"mode": "local", "missing": []}

@app.get("/api/learner-profile")
async def learner_profile_endpoint():
    """통화 시작 때 쓰는 학습자 카드 영어 요약. 카드가 없거나 깨졌으면 빈 요약."""
    try:
        card = await asyncio.to_thread(load_profile)
    except ProfileError as e:
        logger.error(f"Learner profile unreadable: {e}")
        card = None
    return {"brief": profile_brief(card), "updated": card["updated"] if card else None}


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
            _TUTOR_CACHE[cache_key] = (time.time(), data)
            return JSONResponse(data)

        cached = _TUTOR_CACHE.get(path.name)
        if cached and time.time() - cached[0] < _TUTOR_CACHE_TTL_SEC:
            return JSONResponse(cached[1])

        data, saved = await asyncio.to_thread(run_tutoring, path)
        data["saved"] = saved
        _TUTOR_CACHE[path.name] = (time.time(), data)
        # 같은 통화를 다시 분석해도 카드는 한 번만 갱신한다(misses·count 중복 방지).
        if path.name not in _PROFILE_UPDATED:
            _PROFILE_UPDATED.add(path.name)
            _schedule_profile_update({k: v for k, v in data.items() if k != "saved"})
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
async def offer(request: SmallWebRTCRequest, background_tasks: BackgroundTasks):
    """브라우저의 WebRTC offer를 받아 answer를 돌려주고, 새 연결이면 통화 봇을 띄운다."""
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
    await _webrtc.handle_patch_request(request)
    return {"status": "success"}


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
