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

import base64
import asyncio
import json
import os
import re
import logging
import time
import uuid
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
from server.gemini_live import GeminiLive
from server.config_utils import get_project_id
from server.transcript_store import (
    save_transcript,
    get_transcript_dir,
    save_call_audio,
    transcript_stem,
)
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


# Configuration
PROJECT_ID = get_project_id()
LOCATION = os.getenv("LOCATION", "us-central1")
MODEL = os.getenv("MODEL", "gemini-live-2.5-flash-native-audio")

# Initialize FastAPI
app = FastAPI()

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
# In-memory storage for valid session tokens.
# token -> {"created": epoch sec, "limit": 세션 제한 시간(초)}
valid_tokens: Dict[str, dict] = {}
TOKEN_EXPIRY_SECONDS = 30

def cleanup_tokens():
    """Remove expired tokens."""
    current_time = time.time()
    expired = [
        token
        for token, info in valid_tokens.items()
        if current_time - info.get("created", 0) > TOKEN_EXPIRY_SECONDS
    ]
    for token in expired:
        del valid_tokens[token]

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

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    dist_dir = os.path.realpath("dist")
    file_path = os.path.realpath(os.path.join(dist_dir, full_path))
    if full_path and file_path.startswith(dist_dir + os.sep) and os.path.isfile(file_path):
        return FileResponse(file_path)

    return FileResponse("dist/index.html")

@app.post("/api/auth")
async def authenticate(request: Request):
    """
    Issues a temporary one-time session token for the WebSocket connection.
    """
    try:
        data = await request.json()
        if not isinstance(data, dict):
            data = {}
        mode = data.get("mode")

        session_token = str(uuid.uuid4())
        cleanup_tokens()
        # teach-back이면 더 긴 제한 시간을 이 토큰에 묶는다(웹소켓 타임아웃에 씀).
        # 환경변수에서 읽는 로직은 lesson.session_time_limit_from_env 한 곳에 모은다.
        time_limit = session_time_limit_from_env(mode)
        valid_tokens[session_token] = {"created": time.time(), "limit": time_limit}

        return {"session_token": session_token, "session_time_limit": time_limit}
        
    except Exception as e:
        logger.error(f"Auth error: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail="Internal server error")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    """
    WebSocket endpoint for Gemini Live.
    Requires a valid session token generated via /api/auth.
    """
    await websocket.accept()
    
    # Validate Token
    token_info = valid_tokens.get(token) if token else None
    if not token or token_info is None:
        logger.warning("Invalid or missing session token")
        await websocket.close(code=4003, reason="Unauthorized")
        return

    # Remove token (one-time use)
    del valid_tokens[token]

    # /api/auth가 토큰에 묶어 둔 세션 제한 시간을 쓴다(teach-back은 더 길다).
    default_time_limit = session_time_limit_from_env(None)
    try:
        token_time_limit = int(token_info.get("limit", default_time_limit))
    except (TypeError, ValueError, AttributeError):
        token_time_limit = default_time_limit
    
    logger.info("WebSocket connection accepted and authenticated")

    # Wait for initial setup message
    setup_config = None
    try:
        # We expect the first message to be the setup JSON
        message = await websocket.receive_text()
        initial_data = json.loads(message)
        if "setup" in initial_data:
            setup_config = initial_data["setup"]
            logger.info("Received setup configuration from client")
    except Exception as e:
        logger.warning(f"Error receiving setup config: {e}")

    # Call start time and mission title (if present in the system instruction).
    session_start = time.time()
    mission = None
    if setup_config:
        try:
            instruction = setup_config.get("system_instruction", {}).get("parts", [{}])[0].get("text", "")
            match = re.search(r'trying to:\s*"([^"]+)"', instruction or "")
            if match:
                mission = match.group(1)
        except (AttributeError, IndexError, TypeError):
            pass

    audio_input_queue = asyncio.Queue()
    video_input_queue = asyncio.Queue()
    text_input_queue = asyncio.Queue()

    async def audio_output_callback(data):
        await websocket.send_bytes(data)

    async def audio_interrupt_callback():
        # The event queue handles the JSON message, but we might want to do something else here
        pass

    gemini_client = GeminiLive(
        project_id=PROJECT_ID,
        location=LOCATION,
        model=MODEL,
        input_sample_rate=16000
    )

    # 마이크 원음(16kHz·16bit·mono PCM)을 모은다. 상한 30분.
    mic_pcm = bytearray()
    mic_pcm_max = 16000 * 2 * 60 * 30

    async def receive_from_client():
        try:
            while True:
                message = await websocket.receive()
                
                if "bytes" in message and message["bytes"]:
                    if len(mic_pcm) < mic_pcm_max:
                        mic_pcm.extend(message["bytes"])
                    await audio_input_queue.put(message["bytes"])
                elif "text" in message and message["text"]:
                    text = message["text"]
                    try:
                        payload = json.loads(text)
                        if isinstance(payload, dict) and payload.get("type") == "image":
                            # Handle base64 image
                            image_data = base64.b64decode(payload["data"])
                            await video_input_queue.put(image_data)
                            continue
                        elif isinstance(payload, dict) and "realtime_input" in payload:
                             # Forward realtime input (audio/video chunks)
                             # The SDK JS sends 'realtime_input' for generic media chunks
                             # For now we handle simpler case or adapt GeminiLive class
                             pass
                    except json.JSONDecodeError:
                        pass
                    
                    await text_input_queue.put(text)
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error receiving from client: {e}")

    async def run_session():
        async for event in gemini_client.start_session(
            audio_input_queue=audio_input_queue,
            video_input_queue=video_input_queue,
            text_input_queue=text_input_queue,
            audio_output_callback=audio_output_callback,
            audio_interrupt_callback=audio_interrupt_callback,
            setup_config=setup_config
        ):
            if event:
                # Forward events (transcriptions, etc) to client
                await websocket.send_json(event)

    receive_task = asyncio.create_task(receive_from_client())
    session_task = asyncio.create_task(run_session())

    try:
        done, _pending = await asyncio.wait(
            {session_task, receive_task},
            timeout=token_time_limit,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            # Neither task finished: session time limit reached.
            logger.info("Session time limit reached")
            await websocket.close(code=1000, reason="Session time limit reached")
            session_task.cancel()
            try:
                await session_task
            except asyncio.CancelledError:
                pass
        elif receive_task in done and not session_task.done():
            # Client hung up first: cancel the Gemini session instead of
            # letting it run until the time limit.
            session_task.cancel()
            try:
                await session_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Error in Gemini session: {e}")
        else:
            # The Gemini session ended first; surface any error.
            try:
                session_task.result()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Error in Gemini session: {e}")
    finally:
        receive_task.cancel()
        # End of the actual call: record the end time now so the saved
        # transcript duration reflects the real conversation length.
        session_end = time.time()
        started_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(session_start))
        # 마이크 원음 WAV는 전문(.md)보다 먼저 쓴다. /api/tutor는 .md가 생기면
        # 곧바로 분석을 시작하므로, 순서가 반대면 wav를 못 찾는 경합이 생긴다.
        # stem은 save_transcript와 같은 규칙(transcript_stem)으로 미리 계산한다.
        try:
            if mic_pcm:
                audio_path = save_call_audio(bytes(mic_pcm), transcript_stem(started_str))
                if audio_path:
                    logger.info(f"🎙️ Call audio saved: {audio_path}")
        except Exception as e:
            logger.error(f"Call audio save failed: {e}")
        # Save the full conversation as a markdown file (best effort).
        try:
            transcript_dir = get_transcript_dir()
            saved_path = save_transcript(
                gemini_client.transcript_chunks,
                {
                    "started_at": started_str,
                    "duration_sec": int(session_end - session_start),
                    "model": MODEL,
                    "mission": mission,
                    "completed": gemini_client.mission_completed,
                },
                transcript_dir,
            )
            if saved_path:
                logger.info(f"💾 Transcript saved: {saved_path}")
        except Exception as e:
            logger.error(f"Transcript save failed: {e}")
        # Ensure websocket is closed if not already
        try:
            await websocket.close()
        except:
            pass

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8931))
    uvicorn.run(app, host="127.0.0.1", port=port)
