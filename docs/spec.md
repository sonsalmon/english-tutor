# 명세: 나를 기억하는 튜터 (v0.2, 2026-10-20)

상태: 조각 1~3 구현과 첫 학습자 카드 생성을 끝냈다(2026-10-20). 남은 것은 조각 4(정범의 실제 통화)와 조각 5(검증)다. 작업 순서는 10절에 있다.

## 1. 목표

정범 혼자 쓰는 새 영어 통화 앱(`~/dev/english-tutor`)에 고정 튜터 Ms. Park 한 명을 둔다. 튜터는 정범의 수준과 지난 통화를 기억한다. 매 통화를 그 기억에 맞춘다.

immergo(`~/dev/immergo`, 브랜치 english)는 그대로 둔다. 새 앱은 immergo의 통화 코드를 복사해서 시작한다(6절).

## 2. 그림

```
[통화 시작]
   │  서버가 학습자 카드 요약을 준다 (GET /api/learner-profile)
   ▼
[튜터 인사]  "지난번엔 과거형이 헷갈렸어요. 오늘은 ~"  (1~2문장)
   ▼
[상황극]     튜터가 미션 역할로 들어간다. 약점이 나올 상황을 만든다.
   ▼
[튜터 복귀]  역할을 끝내고 짧은 피드백 (30초 안, 쉬운 영어)
   ▼
[통화 종료] → 튜터링(tutoring/*.json, 한국어 요약) → 학습자 카드 갱신
                                                │
                       다음 통화 시작 때 다시 읽음 ◀┘
```

## 3. 사용자가 보는 흐름

1. 미션을 고르거나 "자유 대화"를 고른다.
2. 자유 대화는 오늘 주제를 쓰거나 자료(글·링크 본문)를 붙여 넣는다.
3. 통화가 연결되면 튜터가 먼저 말한다. 지난 약점 1개와 오늘 목표 1개를 말한다.
4. 튜터가 상황극으로 들어간다. 자유 대화는 상황극 없이 주제로 대화한다.
5. 끝나면 튜터가 자기 목소리로 돌아와 쉬운 영어로 짧게 피드백한다.
6. 통화를 끊으면 immergo와 같은 요약 화면이 한국어로 나온다. 뒤에서 카드가 갱신된다.

Teach-back 수업 모드는 코드를 그대로 가져오고 이번 범위에서 바꾸지 않는다.

## 4. 학습자 카드

위치: `~/dev/learning/english/learner-profile.json` (기존 `tutoring/` 옆).

```json
{
  "updated": "2026-10-20T09:00:00+09:00",
  "level": { "cefr": "B1.2", "actfl": "Intermediate High", "source": "level-test 2026-10-07" },
  "weak_points": [
    { "pattern": "과거형 (I just start → started)", "count": 2, "last_seen": "2026-10-16", "example": "I just started my day." }
  ],
  "fixed_points": [],
  "phrases": [ { "phrase": "based out of", "first_seen": "2026-10-16", "used_well": 0 } ],
  "pragmatics": [ { "pattern": "...", "note": "..." } ],
  "interests": [],
  "next_goal": "질문 시제·조동사"
}
```

- `weak_points`는 최대 5개를 둔다. 횟수와 최근성으로 순서를 정한다. 항목마다 선택 정수 `misses`(연속으로 안 나온 통화 수)가 있다.
- 약점이 최근 3회 통화에서 다시 나오지 않으면 `fixed_points`로 옮긴다.
- `level`은 레벨테스트로만 바뀐다. 통화로 자동 변경하지 않는다.
- 카드에는 이름·주소·회사 이름을 넣지 않는다. 카드는 매 통화마다 Google로 간다.

## 5. 동작

- 갱신: 튜터링(`run_tutoring`)이 성공하면 바로 뒤에 한 번 실행한다. 지금 카드와 새 튜터링 JSON을 모델에 주고 갱신된 카드 JSON을 받는다. immergo에서 가져온 `generate_text`(Vertex Gemini)를 쓴다.
- 검사: 받은 JSON이 4절 형식이 아니면 카드를 바꾸지 않는다. 로그를 남긴다.
- 백업: 바꾸기 전 카드를 `~/dev/learning/english/learner-profile-history/<시각>.json`에 복사한다.
- 주입: 통화 시작 때 서버가 카드를 짧은 영어 문단(1,200자 안)으로 바꿔 준다. `view-chat.js`가 미션·재통화·자유 대화 지시문 앞에 Ms. Park 인물 설정과 이 문단을 붙인다.
- 피드백 언어: 통화 안 피드백은 쉬운 영어(B1 수준 어휘, 짧은 문장)로 한다. 통화 뒤 요약 화면과 `tutoring/*.json`의 설명은 한국어로 한다.
- 긴 통화: 통화 서버는 컨텍스트 압축과 세션 재개를 켠다. 압축이 없으면 오디오 통화가 15분에서 끊기고, 연결 1회는 약 10분이다(`~/dev/learning/english/research/2026-10-20-realtime-tutor-stack.md` 2-2절).
- 첫 카드: 기존 튜터링 3개, 10-07 레벨테스트 결과, `learning-records/`로 한 번 만든다(스크립트 1회).

## 6. 에이전트가 정한 것

| 결정 | 이유 | 틀리면 드는 비용 |
|---|---|---|
| 새 앱은 immergo의 통화 코드(FastAPI + google-genai 서버, 브라우저 오디오 워클릿, 받아쓰기 저장, 튜터링)를 복사해서 시작한다. Pipecat은 지금 쓰지 않는다 | immergo 코드는 Vertex Live 연결·끼어들기·받아쓰기·저장이 이미 동작한다. Pipecat은 WebRTC 전송과 새 브라우저 클라이언트가 필요해서 동작하는 오디오 경로를 다시 짜야 한다. 10월 안에 끝내려면 동작하는 길을 재사용한다 | 아바타 2단계(Simli)에서 WebRTC가 필요해지면 전송 계층 교체 1~2일 |
| 빈 저장소에 필요한 파일만 복사한다(커밋 이력은 안 가져옴). Apache-2.0 `LICENSE`와 출처 `NOTICE`를 둔다 | 데모 배포용 코드를 빼고 작게 시작한다 | 옛 이력은 immergo에서 보면 된다 |
| 데모 배포 코드를 뺀다: reCAPTCHA, BigQuery, Redis, 요청 제한(slowapi), 지문(fingerprint), 사용 추적, Dockerfile·Procfile·app.json | 혼자 로컬에서 쓴다 | 외부 공개 때 다시 붙인다 |
| 통화 서버에 컨텍스트 압축 + 세션 재개를 넣는다 | 5절 "긴 통화" | 지금 google-genai 버전에 설정이 없으면 버전을 올린다 |
| 학습 데이터(카드·통화 전문·튜터링)는 앱 저장소 밖 `~/dev/learning/english/`에 둔다 | 지금 기록 위치와 작업실 연결(`workroom sync records`)을 그대로 쓴다 | 없음 |
| 포트 8931 | 8930은 immergo, 8000은 공부 서버, 8787은 collie가 쓴다 | 충돌하면 `PORT` 환경 변수로 바꾼다 |
| 카드는 로컬 JSON 파일 1개 | 기존 tutoring 파일과 같은 폴더·형식 | 작업실 DB로 옮길 때 변환 스크립트 1회 |
| 갱신은 모델이 카드 전체를 다시 씀 + 형식 검사 | 교정 문장을 "과거형" 같은 묶음으로 모으려면 판단이 필요 | 잘못 묶이면 카드 손으로 고침, 백업에서 복구 |
| 레벨은 레벨테스트로만 바꿈 | 통화 한 번으로 레벨이 흔들리면 난이도가 출렁임 | 실력이 빨리 늘면 재시험 전까지 쉬운 대화 |
| 튜터와 상황극 상대가 같은 목소리 | Gemini Live 한 세션은 목소리 1개 | 역할 전환이 덜 분명함, 말로 전환을 알림 |
| 약점마다 `misses`를 두고, `misses`가 3 이상이면 코드가 `fixed_points`로 옮긴다 | "최근 3회 통화에서 안 나오면 옮긴다" 규칙을 코드로 강제하려면 횟수가 필요하다 | 모델이 misses를 잘못 세면 약점이 일찍 또는 늦게 옮겨진다. 카드를 손으로 고친다 |
| 튜터가 먼저 말하게 하려고 연결 직후 텍스트 한 줄 `[The learner just joined the call. Start as Ms. Park.]`을 보낸다 | 기존 텍스트 경로를 쓰므로 서버를 바꿀 필요가 없다 | 모델이 이 줄을 소리 내 읽으면 문구를 고친다 |
| 자유 대화도 끝에 `complete_mission`을 불러 기존 요약 화면을 쓴다 | 요약·튜터링·카드 갱신 흐름을 하나로 유지한다 | 없음 |
| Teach-back 코드는 그대로 복사하고 이번에 바꾸지 않는다 | view-chat.js·app-root.js·main.py·tutor.py에 깊게 얮여 있어 떼어 내는 편이 더 위험하다 | 수업 모드는 기억 없이 지금처럼 동작, 다음 조각에서 기억을 붙임 |

## 7. 사용자 결정 (2026-10-20, 모두 정함)

1. 튜터: Teach-back의 Ms. Park을 고정 튜터로 쓴다. 한국과 미국 문화를 둘 다 아는 선배라서 사고방식 차이를 설명하기 좋다.
2. 피드백 언어: 통화 안 피드백은 쉬운 영어, 통화 뒤 요약 화면은 한국어.
3. 앱 위치: immergo를 키우지 않고 새 앱(`~/dev/english-tutor`)을 만든다.

## 8. 범위 밖

화상·아바타, 미드·유튜브 클립 분석, 억양·강세 채점, 작업실 연결, Teach-back에 기억 붙이기.

## 9. 완료 조건

1. 서버 단위 시험: 카드 갱신(가짜 모델 응답), 형식이 틀린 응답이면 카드 유지, 백업 파일 생성.
2. `scripts/tutor_offline_check.py` 통과, `npm run build` 성공.
3. 실제 통화 1회: 튜터가 첫 말에서 카드의 약점 1개를 말한다. 통화 뒤 `learner-profile.json`의 `updated`가 바뀐다. `sessions/`에 파일이 생긴다.
4. 자유 대화 1회: 붙여 넣은 주제로 대화가 시작된다.
5. 새 문맥 검증자가 이 명세와 변경 내용을 대조한다.

## 10. 작업 순서 (10월)

| 조각 | 내용 | 끝났다는 증거 |
|---|---|---|
| 1. 뼈대 | immergo 통화 경로 복사, 데모 코드 제거, 포트 8931, 압축 + 세션 재개 | `npm run build` 성공, 서버 기동, `scripts/live_smoke.py` 1회 통과 |
| 2. 학습자 카드 | 카드 갱신·형식 검사·백업 + 단위 시험, 첫 카드 만드는 스크립트 | 9절 1번 시험 통과, `learner-profile.json` 생성 |
| 3. Ms. Park + 자유 대화 | 인물 설정·카드 문단 주입, 자유 대화 화면(주제·붙여 넣기) | `tutor_offline_check.py` 통과, 빌드 성공 |
| 4. 실제 통화 | 정범이 미션 통화 1회 + 자유 대화 1회 | 9절 3·4번 |
| 5. 검증 | 새 문맥 검증자 대조 | 9절 5번 |

## 11. Pipecat 전환 (2026-10-20 사용자 결정)

통화 연결 부분만 Pipecat 1.13으로 바꾼다. 학습자 카드, 튜터링, Ms. Park 지시문, 전문 저장 형식, Teach-back은 그대로 둔다. 화면 개편은 12절에서 다룬다.

```
[브라우저] PipecatClient + SmallWebRTCTransport
   │  POST /api/offer (request_data: 지시문·모드·제한 시간)
   ▼
[서버] SmallWebRTCTransport.input → 원음 녹음(AudioBufferProcessor)
        → user aggregator → GeminiLiveVertexLLMService → transport.output → assistant aggregator
   │  턴 이벤트 → 전문 조각, complete_mission → 브라우저에 서버 메시지
   ▼
[통화 끝] sessions/*.md + 원음 WAV → 기존 /api/tutor → 학습자 카드
```

- 없어지는 것: `/api/auth`, `/ws`, `server/gemini_live.py`, `src/lib/gemini-live/*`, 브라우저 오디오 워크릿.
- 새로 생기는 것: `server/call_bot.py`(파이프라인), `POST/PATCH /api/offer`, `src/lib/call-client.js`(브라우저 연결).

| 결정 | 이유 | 틀리면 드는 비용 |
|---|---|---|
| 지시문은 지금처럼 브라우저가 만들어 `/api/offer`의 `request_data`로 보낸다 | `ms-park.js`와 미션·Teach-back 조립 코드를 재사용한다 | 서버로 옮길 때 한 번 이동 |
| 말 차례는 기본으로 Gemini 서버 VAD(10-16 조정값: 시작 민감, 1.2초 침묵)를 쓴다. `TURN_MODE=smart`이면 로컬 Silero VAD + Smart Turn v3.2로 판단한다 | 처음에는 검증된 설정으로 통화하고, Smart Turn은 비교 시험으로 켠다 | Smart Turn이 더 낫으면 기본값만 바꾼다 |
| 세션 재개·컨텍스트 압축은 Pipecat 내장 기능을 쓰고 자체 재연결 코드는 지운다 | 같은 기능을 두 번 갖지 않는다 | 없음 |
| 미션 완료(`complete_mission`)는 서버 함수가 받고 브라우저에 서버 메시지로 알린다 | 전문 머리의 `completed`를 서버가 바로 기록한다 | 없음 |
| 튜터가 먼저 말하는 신호는 서버가 연결 직후 넣는다(Teach-back 제외) | 브라우저 텍스트 경로가 없어진다 | 없음 |
| google-genai를 2.x로 올린다(Pipecat 요구) | 기존 시험 26개가 2.31에서 통과한다 | 없음 |
| 자동 통화 시험: aiortc로 만든 가짜 브라우저가 녹음 음성을 보내고 튜터 음성을 받는다 | 마이크 없이 통화 경로 전체를 확인한다 | 시험 1회에 Vertex 몇 센트 |

완료 조건: 단위 시험, 오프라인 검사 2개, `npm run build`, 자동 통화 시험 1회(튜터가 먼저 말함, `sessions/`에 미션 제목이 들어간 전문, 원음 WAV), 새 문맥 검증.

다음 명세 후보(이번 범위 밖): 아바타 1단계(정지 이미지 + 소리 크기 입 움직임), Teach-back에 기억 붙이기, YouGlish 위젯으로 표현 검색.
