# 들숨 삽입 (실험, `LIVE_BREATHS`, 기본 꺼짐)

## 한 줄 요약

파트너(Gemini Live) 소리에 사람의 들숨이 거의 없어서(Maya 분당 약 2.3회, 우리 3.8은 0.09회), 미리 만든 짧은 들숨 클립을 파트너 말소리 직전에 끼워 넣는다. 스위치를 켜지 않으면 파이프라인은 그대로다.

## 왜 클립을 끼우는가

- 라이브 모델(`gemini-live-2.5-flash-native-audio`, `gemini-3.8-live`)은 `<breath>` 같은 텍스트 태그를 받지 않는다(`research-human.md` 2-1절). 지시문으로 숨소리를 시키는 공식 방법도 없다.
- Gemini 3.8 Flash TTS는 `<breath>` 태그를 지원한다. 그래서 TTS로 클립을 한 번 만들고 통화 중에는 재생만 한다(연구 보고서 3순위 선택지 b).
- 잘못된 자리의 숨소리는 없는 것보다 나쁘다(문장 중간의 숨은 해롭다, Székely 2020). 그래서 개수보다 자리 규칙을 우선한다.

## 켜는 법

```
LIVE_BREATHS=on        # on, 1, true, yes 중 하나. 그 밖의 값이나 미설정이면 꺼짐
```

`server/call_bot.py`의 `run_bot`이 `breath_insert.make_breath_processor(config.voice)`를 `transport.output()` 바로 앞에 끼운다. 꺼져 있으면 파이프라인 구성은 이전과 같고, 켜져 있어도 클립이 없으면(`None`) 끼우지 않는다.

## 놓는 자리 규칙 (`server/breath_insert.py`)

| 규칙 | 값 |
|---|---|
| 자리 1 | 학습자 말에 답하는 파트너 차례의 첫 말소리 직전 |
| 자리 2 | 파트너 차례가 4초 이상 이어진 뒤, 1.2초 이상 이어진 구절 다음의 0.35초 이상 쉼 뒤 말소리 직전 |
| 금지 | 학습자가 말하는 중(마이크 큰 프레임 0.6초 안, 또는 사용자 발화 이벤트), 클립이 없을 때, 학습자 차례가 없었던 첫 인사 |
| 간격 | 마지막 삽입 뒤 15초 안에는 넣지 않는다 |
| 개수 | 삽입 수 + 1이 `2 x 파트너 말한 분 + 0.5`를 넘으면 넣지 않는다(분당 약 2회, 통화 안 첫 삽입은 파트너 말이 15초 쌓인 뒤) |
| 늘어나는 시간 | 클립 최대 0.35초 |
| 크기 | 실제 파트너 말소리 크기(10 ms 프레임 p90)보다 약 36 dB 낮게 맞춘다(Maya 실측 27~49 dB) |

말소리는 10 ms 프레임 레벨 -48 dBFS 초과로 판정한다(파트너 쉼의 잡음은 약 -60 dBFS). 같은 클립을 연달아 쓰지 않는다.

## 클립 만들기 (`scripts/make_breath_clips.py`)

```
.venv/bin/python scripts/make_breath_clips.py [--voices Kore,Leda] [--per-voice 7]
```

1. 파트너 목소리(Kore, Leda, Charon, Iapetus, Sulafat, Fenrir, Zephyr, Achird)마다 `gemini-3.8-flash-tts`(global)로 "Mm-hm. `<breath>` So, what happened next?" 같은 문장 32개를 만든다.
2. 말 사이 쉼에서 약한 무성 잡음 섬을 찾아 0.2~0.34초로 자른다. 레벨은 말소리보다 -28~-47 dB인 것만 쓴다.
3. 자른 클립을 Vertex Gemini 2.5 Flash(오디오 입력)에게 "들숨인가"를 묻고, `INBREATH: yes`만 남긴다(`--no-judge`로 건너뛸 수 있다).
4. 24000 Hz 모노 16비트 WAV로 `server/assets/breaths/<목소리>/bNN.wav`에 저장한다. 전체 2 MB 미만(현재 50개, 약 0.7 MB). 목소리별 개수는 Kore 7, Leda 7, Charon 7, Fenrir 7, Zephyr 7, Achird 6, Sulafat 6, Iapetus 3이다. Iapetus는 쓸 만한 들숨이 적게 나와 3개뿐이다(친구 3명 Jake·Priya·Brian의 목소리가 아니다).

생성은 Vertex 할당량(429)에 자주 걸린다. 스크립트가 기다렸다 다시 시도하며, 만든 TTS 원본은 `/tmp/breath-gen`에 캐시한다.

## 한계 (미확인)

- 클립 음색이 라이브 목소리와 같다는 보증은 없다. 같은 prebuilt 이름을 쓰지만 Gemini TTS와 Live가 같은 음색인지는 문서에 없다.
- 삽입 자리는 오디오 레벨만 보고 정한다. 문장 끝인지 단어 사이 쉼인지 글자로 확인하지 않는다.
- 삽입으로 파트너 말이 최대 0.35초 늦게 이어진다. 응답 간격(response_gap)은 첫 소리(들숨) 시각 기준이라 늘지 않는다.
- 귀로 들어 자연스러운지는 사람이 확인해야 한다. 자동 판정은 Gemini 오디오 판정과 `score_human.py`의 `in_breath` 규칙뿐이다.
