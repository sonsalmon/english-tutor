# 통화 엔진 스위치 계약

정본 설계: `.omo/dag/night-3/design.md` 4절. 이 문서는 서버 구현(`server/call_bot.py`, `server/engines/`)이 지키는 계약만 적는다.

## 요청

`/api/offer`의 `request_data.engine`(문자열).

| 값 | 처리 | 모드 |
|---|---|---|
| (없음 또는 빈 문자열) | `gemini_live`. 오늘 아침 동작과 바이트 단위로 같다 | 모든 모드 |
| `gemini_live` | 기본 경로(`call_bot.run_bot`) | 모든 모드 |
| `gemini_live_notes` | 기본 경로 + 턴 리스너(조언자)가 보내는 감독 메모 | `smalltalk`만 |
| `openai_live` | `server/engines/openai_live.py`(L5) | `smalltalk`만 |
| `cascade_flux` | `server/engines/cascade_flux.py`(L6) | `smalltalk`만 |

`parse_call_config`가 `ValueError`를 내면 `/api/offer`는 400을 돌려준다.

- 모르는 값: `engine은 (...) 중 하나여야 합니다.`
- `smalltalk`가 아닌 모드의 실험 엔진: `실험 엔진은 친구 수다 통화에만 쓸 수 있습니다.`
- 모듈이 아직 없거나 쓸 수 없는 실험 엔진: `이 엔진은 아직 준비되지 않았습니다.` 또는 모듈이 `unavailable_reason()`으로 돌려준 문장(예: API 키 없음).

화면은 기본 엔진이면 `engine` 필드를 보내지 않는다.

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
