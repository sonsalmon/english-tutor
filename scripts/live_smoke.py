# 클라우드 로그인(ADC) + PROJECT_ID로 Vertex Live API 연결이 되는지 한 번 확인한다(소리 1턴 + 받아쓰기).
# 서버와 같은 GeminiLive 경로(컨텍스트 압축·세션 재개 설정 포함)를 쓴다.
import asyncio
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

from server.gemini_live import GeminiLive

load_dotenv(os.path.join(ROOT, '.env'))
project = os.getenv('PROJECT_ID', '')
if not project:
    sys.exit('PROJECT_ID 비어 있음 — .env에 개인 프로젝트 ID를 넣어 주세요')
print(f'프로젝트 {project}, 위치 {os.getenv("LOCATION")}, 모델 {os.getenv("MODEL")}')

live = GeminiLive(project_id=project, location=os.getenv('LOCATION', 'us-central1'), model=os.getenv('MODEL'))


async def first_turn():
    audio = bytearray()
    text = ''
    queues = [asyncio.Queue(), asyncio.Queue(), asyncio.Queue()]
    await queues[2].put('Say exactly: Hello, ready to practice?')
    gen = live.start_session(*queues, audio_output_callback=audio.extend, setup_config={'output_audio_transcription': {}})
    try:
        async for event in gen:
            if event.get('type') == 'error':
                sys.exit(f'오류: {event["error"]}')
            content = event.get('serverContent', {})
            out = content.get('outputTranscription')
            if out and out.get('text'):
                text += out['text']
            if content.get('turnComplete'):
                break
    finally:
        await gen.aclose()
    return audio, text


async def main():
    audio, text = await asyncio.wait_for(first_turn(), timeout=60)
    print(f'OK 소리 {len(audio)}바이트, 받아쓰기: {text.strip()!r}')
    assert audio, '소리가 오지 않음'


asyncio.run(main())
