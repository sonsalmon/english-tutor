#!/bin/bash
# 영어 튜터(Ms. Park) 로컬 실행.
set -e

# 저장소 루트로 이동
cd "$(dirname "$0")/.."

# 서버 포트 (환경 변수 PORT로 덮어쓸 수 있다)
PORT="${PORT:-8931}"

# 포트 사용 여부 확인 (다른 서버와 충돌 방지)
if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "포트 $PORT 사용 중 — PORT=다른번호 로 실행"
  exit 1
fi

# Python 가상환경 확인
if [ ! -x ".venv/bin/python" ]; then
  echo "먼저 uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -r requirements.txt 를 실행하라"
  exit 1
fi

# 프런트엔드 의존성 설치
if [ ! -d "node_modules" ]; then
  npm install
fi

# 프런트엔드 빌드 (서버가 dist/를 서빙한다)
npm run build

# 2초 뒤 브라우저 열기
( sleep 2; open "http://localhost:$PORT" ) &

# 서버 실행 (server/main.py가 dist/를 $PORT에서 서빙)
exec .venv/bin/python -m uvicorn server.main:app --port "$PORT"
