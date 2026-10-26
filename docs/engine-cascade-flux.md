# 엔진 cascade_flux (Deepgram Flux -> Vertex Gemini -> Cartesia sonic-3.6)

정본 설계: `.omo/dag/night-3/design.md` 1.1(C), 3절(C5), 4절. 공통 계약은 `docs/engines.md`. 구현은 `server/engines/cascade_flux.py`다.

친구 수다(`smalltalk`)에서만 쓴다. 요청은 `request_data.engine = "cascade_flux"`다.

## 구성

```
transport.input -> DeepgramFluxSTTService -> user_aggregator -> GoogleVertexLLMService
  -> usage -> CartesiaTTSService -> transport.output -> audiobuffer -> assistant_aggregator
```

| 자리 | 값 |
|---|---|
| STT | `DeepgramFluxSTTService`, 모델 `flux-general-en`, `enable_eager_end_of_turn=True`(예측 종료에 답을 미리 만든다) |
| 집계기 | 표준 모드(`realtime_service_mode=False`). 시작 전략 `MinWordsUserTurnStartStrategy(min_words=3)`, 끝 전략 `EagerUserTurnStopStrategy` |
| LLM | `GoogleVertexLLMService`. 모델은 환경 변수 `CASCADE_LLM_MODEL`(기본 `gemini-2.5-flash`), 프로젝트 `get_project_id()`, 위치 `LOCATION`(기본 `us-central1`). 요청의 system instruction을 그대로 쓴다 |
| TTS | `CartesiaTTSService` 모델 `sonic-3.6`, 영어, 파트너별 목소리 |
| 전문 메타 `model` | `flux+<LLM 모델>+sonic-3.6` |

통화 중 껍데기(전송·녹음·시계·일시정지·텔레메트리·공유 degrade·`finish_call`·기억·요약)는 `engines/shell.py`가 맡는다.

## 끼어들기

파트너가 말하는 동안에는 학습자 말이 3낱말 이상 들려야 파트너를 멈춘다. "mm-hm", "yeah", "oh wow"는 파트너를 멈추지 못한다. 파트너가 말하지 않을 때는 한 낱말도 차례를 시작한다. Flux 자체의 시작 신호는 쓰지 않는다(전략을 직접 지정하면 pipecat은 Flux의 권장 전략을 버린다).

## 목소리 표

Cartesia 문서(Sonic 3.6 "Voice selection")가 음성 에이전트용으로 권하는 안정적인 미국 영어 목소리다.

| 파트너 | 목소리 |
|---|---|
| Jake, Brian | Daniel (`47c38ca4-5f35-497b-b1a3-415245fb35e1`) |
| Priya | Skylar (`db6b0ed5-d5d3-463d-ae85-518a07d3c2b4`) |
| 그 밖 | Jacqueline (`9626c31c-bec5-4cca-baa8-f8ba9e84c8bc`) |

바꾸려면 `PARTNER_VOICES`만 고친다.

## 파트너가 말하는 글

TTS는 받은 글을 전부 읽는다. 그래서 TTS 앞의 글 필터(`spoken_text`)가 `*웃음*`, `(laughs)`, `[laughter]`, `<태그>`, 마크다운 기호, 목록·제목 표시, 이모지를 지운다. 전문(Partner 줄)에도 정리된 글이 남는다. 지시문은 건드리지 않는다.

## 키와 400

서버 환경 변수 `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`가 모두 있어야 한다. 하나라도 없으면 `unavailable_reason()`이 없는 키 이름만 적은 문장을 돌려주고, `parse_call_config`가 이를 `ValueError`로 올려 `/api/offer`가 400으로 답한다. 키 값은 로그·오류 문구·테스트에 쓰지 않는다.

## 턴 지연 로그

Flux가 학습자 차례의 끝(`on_end_of_turn`)을 알린 순간부터 첫 TTS 소리가 나가는 순간까지를 차례마다 한 줄로 남긴다.

```
Turn latency #1: 850 ms (learner end of turn -> first TTS audio)
```

예측 종료(eager)는 답을 미리 만들 뿐, 확정되기 전에는 소리가 나가지 않는다. 그래서 이 값은 "확정 종료 -> 첫 소리"다.

## 건너뛰는 것(계약 4절)

도구 호출, 통화 중 공유(`share_ack ok=false reason=engine`), "생각 중"·"마이크 작음" 알림은 없다. 학습자 목소리의 억양 정보는 STT 글로만 LLM에 전해진다.

## 시험

- 단위: `.venv/bin/python -m unittest server.test_engine_cascade_flux`(네트워크 없음)
- 실통화: `scripts/call_smoke.py --engine cascade_flux --mode smalltalk --seconds 45`
