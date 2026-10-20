# english-tutor

정범 혼자 쓰는 영어 통화 앱. 고정 튜터 Ms. Park이 지난 통화를 기억하고 다음 통화를 맞춘다.

- 명세: `docs/spec.md`
- 출처: immergo(`~/dev/immergo`, Google의 Immersive Language Learning 데모를 고친 것)의 통화 코드를 복사해서 시작했다. `NOTICE` 참고.

## 실행

1. 처음 한 번: `uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -r requirements.txt`
2. `.env`에 `PROJECT_ID`·`LOCATION`·`MODEL`을 넣는다(`.env.example` 참고). 인증은 `gcloud auth application-default login`.
3. `scripts/start.sh` → 브라우저 `http://localhost:8931`

## 데이터 위치 (저장소 밖)

- 통화 전문: `~/dev/learning/english/sessions/`
- 통화 뒤 튜터링: `~/dev/learning/english/tutoring/`
- Teach-back 결과: `~/dev/learning/english/teachback/`
- 학습자 카드: `~/dev/learning/english/learner-profile.json` (바꾸기 전 카드는 `learner-profile-history/`)
- 첫 카드 다시 만들기: `.venv/bin/python scripts/build_learner_profile.py` (미리보기), 저장은 `--write`

## 검사

- 단위 시험: `cd server && ../.venv/bin/python -m unittest test_main_wiring test_learner_profile test_gemini_live test_transcript_store`
- 오프라인 검사: `.venv/bin/python scripts/tutor_offline_check.py`, `.venv/bin/python scripts/teachback_offline_check.py`
- Vertex 연결 시험(소리 1턴, 몇 센트): `.venv/bin/python scripts/live_smoke.py`
- 화면 빌드: `npm run build`
