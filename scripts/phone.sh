#!/bin/bash
# 폰에서 통화할 수 있게 Tailscale로 내 기기끼리만 열리는 HTTPS 주소를 만든다(README "폰에서 통화하기").
# 앱은 먼저 scripts/start.sh로 켜 둔다. 끌 때는 tailscale serve reset.
set -e

PORT="${PORT:-8931}"
TS="$(command -v tailscale || echo /Applications/Tailscale.app/Contents/MacOS/Tailscale)"

if ! "$TS" status >/dev/null 2>&1; then
  echo "Tailscale이 꺼져 있어요. Mac에서 Tailscale 앱을 켜고 로그인한 뒤 다시 실행하세요."
  exit 1
fi

if ! lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "앱이 아직 안 켜져 있어요. 먼저 scripts/start.sh를 실행하세요."
  exit 1
fi

"$TS" serve --bg "$PORT"
echo
echo "폰 브라우저에서 아래 https 주소를 여세요(폰도 Tailscale에 로그인돼 있어야 해요):"
"$TS" serve status
