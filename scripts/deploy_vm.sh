#!/bin/bash
# 클라우드 서버(Google Cloud e2-micro, Tailscale 이름 english-tutor)에 지금 main을 올리고 서비스를 다시 시작한다.
# 학습 데이터는 서버가 원본이다. 원어민 표현 목록만 맥에서 다시 만들었을 때 --native 로 같이 올린다.
#   scripts/deploy_vm.sh            코드·화면만
#   scripts/deploy_vm.sh --native   + ~/dev/learning/english/clipdb/native_expressions.json
set -euo pipefail

cd "$(dirname "$0")/.."

VM_HOST="${VM_HOST:-35.208.171.59}"
VM_USER="${VM_USER:-sonsalmom}"
KEY="${VM_KEY:-$HOME/.ssh/english_tutor_vm}"
SSH=(ssh -i "$KEY" -o ConnectTimeout=15 "$VM_USER@$VM_HOST")

if [ -n "$(git status --porcelain)" ]; then
  echo "커밋 안 한 변경이 있어요. 커밋한 뒤 다시 실행하세요."
  exit 1
fi

npm run build
TAR="$(mktemp -t english-tutor-app).tar.gz"
git archive --format=tar.gz -o "$TAR" HEAD
scp -i "$KEY" -q "$TAR" "$VM_USER@$VM_HOST:/tmp/app.tar.gz"
rm -f "$TAR"
rsync -az --delete -e "ssh -i $KEY" dist/ "$VM_USER@$VM_HOST:english-tutor/dist/"
if [ "${1:-}" = "--native" ]; then
  rsync -az -e "ssh -i $KEY" "$HOME/dev/learning/english/clipdb/native_expressions.json" "$VM_USER@$VM_HOST:dev/learning/english/clipdb/"
fi
"${SSH[@]}" "tar -xzf /tmp/app.tar.gz -C ~/english-tutor && rm /tmp/app.tar.gz \
  && ~/.local/bin/uv pip install -q -p ~/english-tutor/.venv/bin/python -r ~/english-tutor/requirements.txt \
  && sudo systemctl restart english-tutor \
  && for i in \$(seq 1 30); do curl -s -o /dev/null http://127.0.0.1:8931/ && break; sleep 2; done \
  && systemctl is-active english-tutor"
echo "배포 끝: $(git log --oneline -1)"
