# 페르소나 v4: Maya 조언 반영 (night-3, 2026-10-26)

설계 정본: `/Users/sonsalmom/dev/.omo/dag/night-3/design.md` 2절 (P1~P6). 이 문서는 오늘 반영한 것(P1~P3)과 후속으로 미룬 것(P4, P5, P6)을 적는다.

## 오늘 반영한 것

| 번호 | 내용 | 위치 |
|---|---|---|
| P1 | 보이는 친구 셋(Jake, Priya, Brian)의 `VALUES & OPINIONS`에 `STANCE` 추가: 지키는 의견 3개, 정말 싫어하는 것 1개, 이번 주 hot take 1개. 학습자가 반대하면 이유 하나로 한 번 맞서고, 끝까지 고집하면 웃고 넘어간다. 전부 동의하면 같이 고개만 끄덕이지 않고 자기 생각을 붙인다 | `src/lib/partners.ts` 각 친구의 `persona`, `chatPersona` |
| P2 | `NO CHEERLEADING` 한 줄: "wonderful", "amazing", "great job" 금지, 친구답게 "huh", "okay but why", "nah, I don't buy that", "fair" | `src/lib/instructions.ts` `SPEECH_STYLE` |
| P3 | `LISTENING` 추가: 못 알아들으면 추측하지 않고 "Wait, what?", 어려운 질문 뒤 침묵이면 "I'll let you think" 한 번, 질문에는 먼저 답하고 자기 생각 추가, 질문을 연달아 두 번 하지 않기 | `src/lib/instructions.ts` `SPEECH_STYLE` |

숨긴 친구(omar, lukas, carmen, chloe)와 Ms. Park은 건드리지 않았다. 각 친구의 정체성, 신앙(Brian의 `FAITH LIFE`), 배경 이야기는 그대로다.

## 후속으로 미룬 것

- **P4 교정 기본값**: Ms. Park의 `DEFAULT_CORRECTION`을 `normal`에서 `light`로 바꿀지는 사용자 결정이다. 결정 전에는 `src/lib/coachSettings.ts`를 바꾸지 않는다.
- **P5 압박 있는 페르소나** (Maya 조언: 실제 직장에서 만날 사람들): 편한 친구만으로는 해외 직장에서 듣게 될 말투를 연습할 수 없다. 후속 티켓 후보:
  1. 바쁜 매니저: 시간이 없어서 용건부터 말하고, 한 번에 지시를 여러 개 준다. 학습자가 되물어야 한다.
  2. 직설적인 선배: 돌려 말하지 않고 "That won't work, here's why"라고 한다. 감정이 아니라 일 이야기다.
  3. 회의 진행자: 말을 끊고 요약해서 되묻는다("So you're saying...?").
  4. 공통 조건: 통화 중 교정은 하지 않는다. 압박은 속도와 직설에서만 나오고, 무례함으로 가지 않는다. 학습자가 고르는 별도 모드로 두고 친구 수다 기본값에는 넣지 않는다.
- **P6 감독 메모 문단**: 서버 `gemini_live_notes` 엔진이 붙인다(L3 레인 담당). 클라이언트 지시문에는 넣지 않는다.
