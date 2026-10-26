# 말투 지시문 (VOICE STYLE)

친구 수다 통화의 말소리를 Maya(Sesame 통화 한 건)에 가깝게 하려고, 시스템 지시문 끝에 짧은 영어 블록을 붙인다. 라이브 모델은 텍스트 태그를 받지 않으므로(`.omo/dag/n5-human-voice/research-human.md`) 지시문이 유일한 서버 쪽 수단이다. 턴 넘기기 코드(`server/call_bot.py`)는 건드리지 않는다.

## 동작

- 코드: `server/voice_style.py`의 `with_voice_style(config, mode)`. `server/main.py`의 `/api/offer`가 `resume.with_resume` 바로 뒤에서 한 번 부른다.
- 적용 대상: `call_bot.CHAT_MODES`(`smalltalk`, `freetalk`) 통화, 두 엔진(`gemini_live`, `gemini_live_38`) 모두. 미션, Teach-back, 그 밖의 모드는 설정 객체가 그대로 돌아온다.
- 붙는 자리: 지시문 + 이어 가기 블록(`resume`) 뒤. 엔진이 통화 시작 때 덧붙이는 조용한 조언자 접미사(`call_bot.py`)는 그 뒤에 붙으므로 말투 블록은 그보다 앞에 놓인다.
- 서버 로그: `Voice style applied: mode=… engine=… partner=… +N words` 한 줄(INFO).
- 같은 지시문에 이미 블록이 있으면 다시 붙이지 않는다.

## 스위치

환경변수 `LIVE_VOICE_STYLE`. 기본 켜짐. `off`, `0`, `false`, `no`(대소문자 무관)이면 꺼지고, 그때 지시문은 이전과 바이트까지 같다. 서버를 다시 띄워야 바뀐다.

## 지시문이 겨냥하는 요소

| 문장 | 겨냥하는 BEFORE 점수 요소 |
|---|---|
| 넷 중 하나쯤은 Oh, Gotcha, Exactly, Right?로 시작 | turn_start_reaction_words (3.8: 0.6/분, Maya 1.7) |
| 느긋한 대화 음높이, 과장된 오르내림 금지 | pitch_variation (13.7반음, Maya 8.4) |
| 문장 끝까지 힘 유지 | trailing_off (16~18/분, 상한 11) |
| 생각 사이 짧은 자연스러운 쉼 | pause_length_in_turn (3.8: 0.39초, 띠 0.40~0.80) |
| 군소리는 드물게, 지문·태그 읽지 않기 | fillers_um_uh, 위험 목록(지문 낭독) |

글자 수 상한은 120단어(`MAX_WORDS`)이고 시험이 지킨다. 문구 자체는 시험으로 고정하지 않는다.

## 운율 블록 (PROSODY, 실험 스위치)

- 환경변수 `LIVE_PROSODY_STYLE`. 기본 꺼짐. `on`처럼 꺼짐 값(`off`, `0`, `false`, `no`) 밖이면 켜진다. 꺼지면 지시문은 위 VOICE STYLE까지만 붙은 상태와 바이트까지 같다.
- 켜지면 같은 함수가 VOICE STYLE 뒤에 영어 블록 `PROSODY_STYLE`(80단어 이하, `PROSODY_MAX_WORDS`)을 붙이고 `Prosody style applied: …` 로그를 한 줄 남긴다. VOICE STYLE을 꺼도 단독으로 붙는다.
- 형용사 대신 행동을 적는다: 한 턴 1~2문장과 and/so/but 잇기, 생각 중간 쉼에서 마지막 단어 높이 유지, 평서문은 중간 높이에서 끝내고 턴 마지막 문장만 끝까지 내리기, 새 문장은 앞 문장이 끝난 높이 근처에서 시작, 강조는 높이 대신 길이.
- 겨냥하는 지표(`.omo/dag/n5-human-voice/replica/prosody-metrics.md`): 이어 가는 구 끝 움직임, 문장 끝 움직임과 하강 비율, 재설정 폭, 강조 돌출. 설계와 측정은 `lanes/prosody-impl-design.md`, `lanes/prosody-impl-report.md`.

## 한계

- 효과는 지시문 준수에 달려 있다. 문헌상 지시문이 길면 준수가 떨어진다고 하여 짧게 유지했다.
- `freetalk`는 파트너 없이 걸리는 경우(Ms. Park 자유 대화)도 같은 모드 묶음에 들어간다. 코드가 이미 이 묶음을 대화 모드로 다루므로 따랐다. Ms. Park 자유 대화에서 빼야 하면 `config.partner` 조건을 `with_voice_style`에 넣으면 된다.
- 측정값은 `.omo/dag/n5-human-voice/lanes/H1-report.md`에 있다.
