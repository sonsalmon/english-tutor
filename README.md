# english-tutor

정범 혼자 쓰는 영어 통화 앱. 고정 튜터 Ms. Park이 지난 통화를 기억하고 다음 통화를 맞춘다.

- 명세: `docs/spec.md` (11절 Pipecat 통화, 12절 화면·폰 접속)
- 출처: immergo(`~/dev/immergo`, Google의 Immersive Language Learning 데모를 고친 것)에서 시작했다. `NOTICE` 참고.
- 구성: 서버 FastAPI + Pipecat 1.13(Gemini Live on Vertex, SmallWebRTC), 화면 React + TypeScript + Tailwind(Vite).

## 실행 (Mac)

1. 처음 한 번:
   - `uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -r requirements.txt`
   - `npm install`
2. `.env`에 `PROJECT_ID`·`LOCATION`·`MODEL`을 넣는다(`.env.example` 참고). 인증은 `gcloud auth application-default login`.
3. `scripts/start.sh` → 브라우저 `http://localhost:8931`

말 차례 판단은 기본으로 Gemini가 한다. 로컬 Smart Turn으로 비교해 보려면 `TURN_MODE=smart scripts/start.sh`.

## 폰에서 통화하기 (Tailscale)

폰 마이크는 HTTPS 주소에서만 켜진다. 이미 설치된 Tailscale로 내 기기끼리만 열리는 HTTPS 주소를 만든다.

1. Mac에서 Tailscale 앱을 켜고 로그인한다.
2. Tailscale 관리 화면(https://login.tailscale.com/admin/dns)에서 MagicDNS와 HTTPS Certificates를 켠다(처음 한 번).
3. 폰에 Tailscale 앱을 설치하고 같은 계정으로 로그인한다.
4. Mac에서 `scripts/start.sh`로 앱을 켠 뒤, 다른 터미널에서 `scripts/phone.sh`를 실행한다. 화면에 나온 `https://...ts.net` 주소를 폰 브라우저로 연다.
5. 그만 열어 두려면 `tailscale serve reset`.

## 데이터 위치 (저장소 밖)

- 통화 전문: `~/dev/learning/english/sessions/`
- 통화 뒤 튜터링: `~/dev/learning/english/tutoring/`
- Teach-back 결과: `~/dev/learning/english/teachback/`
- 학습자 카드: `~/dev/learning/english/learner-profile.json` (바꾸기 전 카드는 `learner-profile-history/`)
- 첫 카드 다시 만들기: `.venv/bin/python scripts/build_learner_profile.py` (미리보기), 저장은 `--write`

## 검사

- 단위 시험: `cd server && ../.venv/bin/python -m unittest test_call_bot test_main_wiring test_learner_profile test_transcript_store`
- 오프라인 검사: `.venv/bin/python scripts/tutor_offline_check.py`, `.venv/bin/python scripts/teachback_offline_check.py`
- 화면 빌드(타입 검사 포함): `npm run build`
- 통화 경로 시험(Vertex 몇 센트, 마이크 없이 가짜 브라우저가 통화): 서버를 임시 폴더로 띄운 뒤 `TRANSCRIPT_DIR=... AUDIO_DIR=... .venv/bin/python scripts/call_smoke.py --url http://127.0.0.1:<포트>`
