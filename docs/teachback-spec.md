# 가르치며 배우기(Teach-back) 수업 모드 — 명세

목표: 사용자가 그날 공부한 보안 내용을 영어로 **가르친다**(파인만 공부법). 미국 중학생 3명(AI)이 모르는 말·건너뛴 설명에 질문한다. 선배 선생님(=영어 튜터)이 수업 중에 끼어들거나(기본) 수업 뒤에 피드백한다(설정). 답하지 못한 질문은 원인(영어/이해)과 함께 기록한다.

## 흐름
1. 미션 목록에서 "Teach-back: Today's Lesson"을 고른다.
2. 수업 준비 화면: 수업 날짜 고르기(최근 기록 날짜들), 그날 기록의 절 제목 미리보기, "선배 선생님 개입: 수업 중 / 수업 후" 토글(기본 수업 중, 브라우저 localStorage `teachback.seniorMode` = `during`|`after`).
3. Start Mission(기존처럼 눌러야 시작·과금). 수업 시간 15분.
4. 끝나면 요약 화면: "답 못한 질문"(원인 배지) → 기존 튜터링 4칸 → "같은 수업 다시 하기".

## 계약 1: `GET /api/lesson?date=YYYY-MM-DD` (date 생략 시 가장 최근)
200:
```json
{
  "topic": "security-career",
  "date": "2026-10-12",
  "dates": ["2026-10-12", "2026-10-08", "..."],
  "day_title": "…",
  "sections": [{"heading": "…", "body": "…"}],
  "hidden_count": 0
}
```
- 원본: `~/dev/learning/security-career/learning-records/<날짜>.md`. `dates`는 최근 7개.
- 거르기는 작업실 코드를 **재사용**한다: `workroom_cli.records.day_rows(topic, date, text, blocked)` + `workroom_cli.filters.load_blocklist(data_dir)`. `filtered: true` 행은 빼고 개수를 `hidden_count`로. 거름망을 다시 구현하지 않는다.
- 호출 방식: 서버가 `python3 scripts/lesson_dump.py --date …`를 **하위 프로세스**로 실행하고 `PYTHONPATH=<WORKROOM_CLI_DIR>`(환경변수, 기본 `~/dev/workroom/cli`)를 넘긴다. 차단어 파일 위치는 `WORKROOM_DATA_DIR`(기본 `~/.workroom`). 학습 폴더는 `LEARNING_ROOT`(기본 `~/dev/learning`).
- 차단어 목록이 없거나 깨졌으면 500 + 한국어 메시지. **거르지 않은 원문으로 대체하지 않는다.**
- 기록이 없으면 404 + 한국어 메시지.
- `date`는 `^\d{4}-\d{2}-\d{2}$`(ASCII, fullmatch)만 받는다.
- 모델에 넘길 수업 글은 절 본문 합쳐 최대 6000자에서 자른다(서버 함수 `lesson_text(lesson) -> str`).

## 계약 2: `POST /api/auth` 확장
- 본문에 `"mode": "teachback"`이 있으면 이 세션의 제한 시간은 `TEACHBACK_TIME_LIMIT`(기본 900초), 아니면 기존 `SESSION_TIME_LIMIT`. 응답의 `session_time_limit`도 그 값. 웹소켓 세션 타임아웃이 토큰에 묶인 값을 쓴다.

## 계약 3: `POST /api/tutor` 확장
요청: `{"started_at": <ms>, "mode": "teachback", "lesson_date": "YYYY-MM-DD"}` (mode 없으면 기존 동작 그대로).
teachback 응답 = 기존 5키 + 아래 두 키 + `saved`:
```json
{
  "unanswered": [
    {"question": "Maya: …", "teacher_said": "짧은 인용", "cause": "english|understanding|both|unclear",
     "evidence": "한국어 한 줄 근거", "parked": true}
  ],
  "lesson_date": "2026-10-12"
}
```
- 저장 위치: `~/dev/learning/english/teachback/<전사 파일 stem>.json` (tutoring/ 아님).
- 분석 프롬프트(영어 모델 지시, 결과 설명은 한국어):
  - 화자 줄은 `**Me:**`(선생님=사용자)와 `**Partner:**`(학생들과 선배). Partner 줄 안에서 "Maya:", "Leo:", "Sam:"으로 학생을, "Quick note from Ms. Park"로 선배를 구분한다.
  - 학생 질문마다, 선생님 답이 13살이 이해할 만큼 충분했는지 판단한다. 충분하면 넣지 않는다.
  - cause: `english` = 내용은 아는 듯한데 영어로 못 냄(한국어로 빠짐, "how do you say", 오래 막힘, 노트와 맞는 조각은 있음) / `understanding` = 내용이 노트와 다르거나 모호·순환 설명·"I don't know" / `both` / `unclear`.
  - `parked` = 선생님이 "let me check and get back to you" 류로 미룬 질문.
  - 숨은 노트(수업 글)를 정답지로 쓴다. 노트에 없는 내용은 understanding 판정 근거로 쓰지 않는다.
  - 선배(Ms. Park)의 개입 문장은 corrections 근거로 반영한다.
  - 최대 개수: unanswered 8.
- `retry`는 teachback이면: goal = 다음 수업에서 고칠 점, target_phrases = 써 볼 표현. 프런트는 "같은 수업 다시 하기" 때 unanswered 질문들을 학생들이 다시 물어보게 지시문에 넣는다.

## 수업 지시문(프런트가 조립, 모델에 보냄)
teachback 미션은 일반 롤플레이 지시문 대신 아래 틀을 쓴다(언어·받아쓰기 설정은 그대로). `{SENIOR_BLOCK}`은 모드에 따라 고른다.

```
TEACH-BACK LESSON MODE
The user is the TEACHER. You play a class of three American middle school students (about 13):
Maya (curious, asks "Why?"), Leo (asks "Wait, what does ___ mean?"), Sam (asks for an everyday example or "So what?").
The teacher explains today's topic in English.

Rules for the students:
- You only know what the teacher has said in this class. You have NOT read the notes below. Never explain the topic yourselves and never correct the teacher's content directly.
- When the teacher uses a term, acronym or jargon that was not defined yet, a student asks what it means. When a step is skipped or a claim has no reason, ask "Why?" or "How does that work?". When something is abstract, ask for an everyday example.
- One student per turn. Start each turn with the student's name, e.g. "Leo: Wait, what's a ...?". Keep it short and kid-like. Let the teacher finish a point before asking. At most one question per turn.
- Use the hidden notes only to notice where the explanation is missing, vague, or contradicts the notes, then ask a naive question that leads there. Never reveal or quote the notes.
- If the teacher says something like "Good question - let me check and get back to you", the student says "Okay, cool!" and the class moves on.
- If the teacher switches to Korean, a student says "Sorry, we don't speak Korean - can you say it in English?".
- When the teacher wraps up, Sam asks: "So what's the one main thing we should remember?"
- Start the class with Maya saying: "Hi! So what are we learning today?"

{SENIOR_BLOCK}

Hidden notes (the teacher's own study notes; for you only):
<<<
{LESSON_TEXT}
>>>
{RETRY_BLOCK}
```

SENIOR_BLOCK (during):
```
There is also a senior teacher, Ms. Park, at the back of the room. She is the teacher's English mentor.
She speaks ONLY when the teacher's English makes the explanation hard to understand: a wrong word, confusing grammar, a Korean-style phrase an American would misread, or the teacher is stuck for more than about 8 seconds.
She always starts with "Quick note from Ms. Park -", gives ONE short suggestion (the better English phrase), and ends with "Back to you." At most once every two minutes. She never comments on the content of the lesson.
```
SENIOR_BLOCK (after):
```
A senior teacher, Ms. Park, is in the room but stays completely silent during the class.
```
RETRY_BLOCK(다시 하기일 때만): 지난 수업의 goal·target_phrases와 "Students should ask these questions again at a natural moment:" + unanswered 질문 목록.

## 안 할 것
- 수업 뒤 선배와의 음성 튜터링 통화(2차).
- 작업실(workroom) 저장소 수정, 작업실 DB 쓰기. 기록 옮기기는 메인 에이전트가 세션 끝에 한다.
- 인증·CORS·바인딩 변경, 새 의존성.

## 완료 조건
- `GET /api/lesson`이 거른 절만 돌려준다(차단어에 걸리는 가짜 절을 넣은 임시 폴더로 오프라인 점검).
- teachback 세션 제한 900초, 일반은 기존 값.
- `/api/tutor` teachback 결과가 계약 키를 갖고 `teachback/`에 저장된다(모델 없이 스텁으로 점검 + 메인이 실제 1회).
- 미션 목록 → 준비 화면 → 통화 → 요약(답 못한 질문 섹션) 화면 연결, 토글 저장.
- `npm run build` 통과(메인이 실행), 브라우저에서 준비 화면과 요약 화면이 그려짐(메인 확인).

## 에이전트가 정한 것
- 거름망은 작업실 코드를 하위 프로세스로 재사용 — 두 저장소 가상환경이 달라 import보다 안전 — 작업실 함수 이름이 바뀌면 lesson_dump.py 한 파일만 고치면 됨.
- 선배 개입은 같은 음성 세션 안의 역할 + 신호 문구 — 별도 모델·화면 없이 됨 — 목소리가 학생과 같아 헷갈리면 화면 카드 방식으로 바꿈.
- 학생·선배 구분은 이름 접두어로 — 음성 받아쓰기는 화자를 안 나눔 — 모델이 접두어를 빠뜨리면 분석 정확도가 떨어짐.
