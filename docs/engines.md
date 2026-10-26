# 통화 엔진 스위치 계약

정본 설계: `.omo/dag/night-3/design.md` 4절. 이 문서는 서버 구현(`server/call_bot.py`, `server/engines/`)이 지키는 계약만 적는다.

## 요청

`/api/offer`의 `request_data.engine`(문자열).

| 값 | 처리 | 모드 |
|---|---|---|
| (없음 또는 빈 문자열) | `gemini_live`. 오늘 아침 동작과 바이트 단위로 같다 | 모든 모드 |
| `gemini_live` | 기본 경로(`call_bot.run_bot`) | 모든 모드 |
| `gemini_live_notes` | 기본 경로 + 턴 리스너(조언자)가 보내는 감독 메모 | `smalltalk`만 |
| `gemini_live_38` | 기본 경로(`GEMINI_ENGINES`). 이 통화만 모델 `gemini-3.8-live`, 감정 대화(`enable_affective_dialog`) 끔 | `smalltalk`만 |
| `openai_live` | `server/engines/openai_live.py`(L5) | `smalltalk`만 |
| `cascade_flux` | `server/engines/cascade_flux.py`(L6) | `smalltalk`만 |

`parse_call_config`가 `ValueError`를 내면 `/api/offer`는 400을 돌려준다.

- 모르는 값: `engine은 (...) 중 하나여야 합니다.`
- `smalltalk`가 아닌 모드의 실험 엔진: `실험 엔진은 친구 수다 통화에만 쓸 수 있습니다.`
- 모듈이 아직 없거나 쓸 수 없는 실험 엔진: `이 엔진은 아직 준비되지 않았습니다.` 또는 모듈이 `unavailable_reason()`으로 돌려준 문장(예: API 키 없음).

화면은 기본 엔진이면 `engine` 필드를 보내지 않는다.

### `gemini_live_38`

- 모델: `call_bot.live_model_for(mode, env, engine)`이 엔진이 `gemini_live_38`이면 환경 변수와 상관없이 `gemini-3.8-live`(`base.LIVE_38_MODEL`)를 돌려준다. 다른 엔진은 지금처럼 `LIVE_MODEL_CHAT`·`LIVE_MODEL`·`MODEL`을 따른다.
- 감정 대화: 3.8은 `enable_affective_dialog`를 1007로 거부하므로 `affective_dialog_from_env(env, engine)`이 이 엔진에서는 늘 끈다. 다른 엔진은 `LIVE_AFFECTIVE_DIALOG`를 따른다(기본 켬).
- 전문 메타 `model`에는 실제로 쓴 모델(`gemini-3.8-live`)이 적힌다.

## 화면에 보이는 엔진

설정 화면(`src/screens/Settings.tsx`)은 `src/lib/engineSettings.ts`의 `VISIBLE_CALL_ENGINES` 한 곳에 든 엔진만 보인다: `gemini_live`(기본)와 `gemini_live_38`("새 모델: Gemini 3.8 Live"). `gemini_live_notes`, `cascade_flux`, `openai_live`는 서버·클라이언트 코드에 남기고 화면에서만 숨긴다(night-3 replica-diff: 조언자는 메모가 늦고 조립식은 응답이 느려 탈락).

- 저장된 값이 보이는 목록에 없으면 `loadCallEngine`이 기본 엔진으로 본다. 그래서 `engine` 필드를 보내지 않는다.
- 숨긴 엔진을 다시 보이려면 `VISIBLE_CALL_ENGINES`에 이름을 넣고 `Settings.tsx`의 `ENGINE_TEXT` 문구를 확인한다.

## 서버 구조

- `server/engines/base.py`: 엔진 이름·`EngineParts`·`NoteSink`/`TurnListener` Protocol·`engine_unavailable_reason`. pipecat을 불러오지 않는다.
- `server/engines/__init__.py`: `ENGINES`(이름 → 모듈 경로, 지연 import)와 `run_engine(webrtc_connection, config)`.
- `server/engines/shell.py`: 실험 엔진 공통 껍데기. 전송(SmallWebRTC)·집계기 쌍·`AudioBufferProcessor`·`CallClock`·pause/resume/telemetry·`finish_call`·친구 기억·요약 정리를 맡는다. 기본 경로에서 코드를 옮기지 않고 새로 썼다.
- `call_bot.run_bot`의 변경은 첫 줄 분기(`config.engine not in GEMINI_ENGINES` → `engines.run_engine`), 턴 리스너 호출 3곳(만들기·`attach(llm)`·`on_user_turn`), `TranscriptHintedLiveService.send_note()`뿐이다.

### 엔진 모듈 계약

모듈은 `build_parts(config) -> EngineParts`를 가진다. `EngineParts(model_name, llm, stt=None, tts=None, user_params=None, realtime_service_mode=True, audio_out_sample_rate=None)`.
shell 파이프라인: `transport.input → [stt] → user_aggregator → llm → usage → [tts] → transport.output → audiobuffer → assistant_aggregator`.
선택으로 `unavailable_reason() -> Optional[str]`를 둘 수 있다(키가 없으면 문장을 돌려준다). `build_parts`가 실패하면 `run_engine`이 로그를 남기고 연결을 끊는다.

### 턴 리스너와 감독 메모

`call_bot.configure_turn_listener(factory)`로 등록한다(`configure_call_saved`와 같은 모양). `factory(config, record) -> TurnListener | None`이고 None이면 그 통화는 지금과 같다.
`TurnListener`는 `instruction_suffix: str`(지시문 끝에 붙는다), `attach(note_sink)`(LLM 서비스를 만든 직후), `async on_user_turn(text)`(학습자 차례가 전문에 남을 때)을 가진다. 리스너 실패는 통화를 막지 않는다.
`send_note(text)`는 세션에 `send_client_content(turn_complete=False)`로 메모를 넣는다(자막·전문에 섞이지 않는다). 파트너가 말하는 중이면 그 차례의 `turn_complete` 뒤로 미룬다.

## 입력 이득·끼어들기 게이트·침묵 재참여 (묶음 4, Gemini 엔진 전용)

`call_bot.run_bot`을 타는 Gemini 엔진(`gemini_live`, `gemini_live_notes`, `gemini_live_38`)에만 적용한다. 새 기본값은 운영 동작을 바꾼다. 세 스위치를 모두 꺼면 이번 묶음 이전 통화 경로와 같다.

| 환경 변수 | 기본 | 끄는 값 | 뜻 |
|---|---|---|---|
| `LIVE_INPUT_GAIN` | `auto` | `off` | 전송 계층 입력 이득(`server/audio_gain.py`). 말소리만 목표 레벨까지 끌어올리고 잡음·디지털 무음은 키우지 않는다. 이득 → RNNoise 순서 |
| `LIVE_INPUT_GAIN_TARGET_DBFS` / `_MAX_DB` / `LIVE_INPUT_GATE_DBFS` | -20 / 18 / -50 | | 목표 레벨, 최대 이득(dB), 말소리로 보는 최소 레벨 |
| `LIVE_BARGE_IN_MODE` | `vad` | `words` | `vad` = 로컬 Silero 게이트(`server/barge_in.py`) + 낱말 보조, `words` = 낱말만(묶음 3 동작), `native` = Gemini 기본 끊기(`LIVE_BARGE_IN_WORDS=0`과 같다) |
| `LIVE_BARGE_IN_MIN_VOICED_MS` / `_CONFIDENCE` / `_MIN_DBFS` | 700 / 0.7 / -40 | | 유성음이 이 길이 이상 이어지면 상대를 멈춘다. 200 ms 이하 끊김은 잇는다 |
| `LIVE_SILENCE_REENGAGE_SEC` | `10` | `0` | smalltalk·freetalk에서 상대 말이 끝난 뒤 학습자가 이 초 동안 말하지 않으면 서버가 `[Silence note: ...]`를 보내 상대가 내용 있는 말을 먼저 꺼내게 한다 |
| `LIVE_SILENCE_REENGAGE_MAX` | `2` | | 학습자가 말하기 전 연속 재참여 최대 횟수 |
| `LIVE_PROACTIVE_AUDIO` | `off` | `on` | 기본은 끔: 모든 Gemini 엔진에 `proactivity`를 주지 않는다. 2.5에서 선제 오디오를 켜면 모델이 대답하지 않기로 해 재참여가 필요한 무응답이 났다(P3 A/B). `on` = 옛 동작(`ProactivityConfig(proactive_audio=True)`). 이 스위치만은 "끄는 값" 칸이 옛 동작 값이다. 시작 로그 `Proactive audio: on\|off` |

- `vad` 모드는 Gemini에 `NO_INTERRUPTION`을 주고 끊기는 서버가 한다. `LIVE_BARGE_IN_WORDS=0`이면 모드가 무엇이든 Gemini 기본 끊기(`native`)다. `TURN_MODE=smart`(Gemini VAD 끈 상태)에서는 게이트를 쓰지 않는다.
- 침묵 재참여는 `turn_complete=True`로 보내 Gemini가 바로 이어 말한다. 전문에는 `**system:** silence re-engage #N at <초>s`로 남고 `[Silence note:` 로 시작하는 받아쓰기는 학습자 발화에서 버린다. 일시정지 중에는 지나지 않는다.
- 전문 메타 `- vad:` 줄 끝에 켜진 장치가 `barge=vad gain=auto reengage=10s`처럼 붙는다(전부 꺼져 있으면 붙지 않는다).
- 서버 로그: 시작 시 `Input gain auto (...)`, `Barge-in gate armed (vad, 700 ms)`, `Silence re-engage armed (10 s)`; 발동 시 `Barge-in: ... -> interrupt`, `Silence re-engage #N ...`; 상대 차례마다 `Turn complete: <초> after the partner's first sound; <N> input transcript chunk(s) arrived while the partner spoke`(3.8이 겹친 음성을 버리는지 가리는 진단).

## 모든 엔진이 지키는 것

1. 전사 조각: 학습자 `("Me", text)`, 파트너 `("Partner", text)`가 `CallRecord.chunks`에 쌓인다. 마이크 원음은 `record.mic_pcm`.
2. 통화 끝: `finish_call(record, config, model_name, vad=None)`. 전문 메타 `model`에 엔진 모델 이름. `pricing`이 모르는 이름이면 `cost_usd`는 None.
3. 통화 뒤: `schedule_partner_memory_update`, `notify_call_saved`를 같은 순서로 부른다.
4. 이어 가기: `/api/offer`의 `resume.with_resume`가 엔진보다 먼저 지시문을 고친다.
5. RTVI 자막(`bot-output`, `user-transcription`)이 와야 한다. 일시정지·재개·시간 제한·텔레메트리는 shell이 처리한다.

## 실험 엔진이 오늘 건너뛰는 것

- 에이전트 도구(`recall_past_conversations`, `share_clip`, `complete_mission`): 등록하지 않는다.
- 통화 중 공유(`share`): `share_ack`를 `ok=false, reason="engine"`으로 답하고 전문에 `Me (shared)` 줄만 남긴다.
- "생각 중"·"마이크 작음" 알림: 내지 않는다.

## 시험

`scripts/call_smoke.py --engine <값> --mode smalltalk`. `--engine`을 주지 않으면 필드를 보내지 않는다(기본 경로). 실험 엔진은 전문에 `**Partner:**` 줄이 있어야 `SMOKE OK`다.
