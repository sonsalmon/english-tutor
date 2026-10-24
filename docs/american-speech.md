# 미국인 친구와 구어체 말투 (2026-10-24)

친구 7명(priya, jake, brian, omar, lukas, carmen, chloe)은 모두 미국에서 태어나 자란 사람이고, General American 억양으로 말합니다. 통화 지시문에는 공통 `SPEECH STYLE` 블록이 한 번만 들어갑니다. 근거는 `.omo/dag/night-1/research-speech.md`(2026-10-24 조사)입니다.

표기: **[확인]**은 출처 문장을 직접 읽은 항목이고, **[미확인]**은 일반 언어학 상식이라 방향만 참고하는 항목입니다.

## 1. 무엇이 바뀌었나

- `src/lib/partners.ts`: 영어 변종 지시(`ENGLISH VARIETY`의 인도·케냐·요르단·독일·스페인·캐나다·중서부 영어)와 외래 말버릇(na?, yaar, arre, sasa, poa, pole pole, sawa, aki, yani, inshallah, wallah, vale, venga, claro, washroom, toque)을 모두 지우고, `HOW YOU SOUND`(General American, 지역색은 도시 수준)로 바꿨습니다.
- `src/lib/instructions.ts`: `SPEECH_STYLE` 상수를 `partnerPrefix`에서 `PARTNER_RULES` 뒤에 한 번 넣습니다. 친구 통화(수다, 자유 대화, 상황 롤플레이)에만 들어가고 문자 채팅과 Ms. Park에는 들어가지 않습니다.
- 목소리와 초상화는 그대로입니다. 조사에서도 7명 모두 유지를 권했습니다.

## 2. 친구별 새 배경

| 친구 | 새 배경 |
|---|---|
| Priya | 인도계 미국인, 뉴저지 에디슨 출생, 가족 뿌리는 벵갈루루, 최근 2년을 벵갈루루 지사에서 일하다 오스틴으로 이사 |
| Brian | 케냐계 미국인, 미니애폴리스 출생, 나이로비에서 2년(마타투를 탐), 휴스턴으로 이사 |
| Jake | 오하이오 컬럼버스(변동 없음) |
| Omar | 아랍계 미국인, 미시간 디어본 출생, 부모는 암만 출신 |
| Lukas | 독일계 미국인, 위스콘신 밀워키 |
| Carmen | 쿠바계 미국인, 마이애미 출생, 사우스캐롤라이나 찰스턴 거주 |
| Chloe | 일리노이 시카고 |

Priya와 Brian은 이미 학습자와 통화했습니다. 그때 들은 사실(Priya의 오스틴 이사, 쿠드레무크 트레킹, 아버지의 크리켓 전화, Brian의 야간 보안 분석가, 나이로비에서 휴스턴 이사, 마타투, 교회 이야기)이 새 배경과 모순되지 않도록 지시문에 "그 말은 사실이니 그대로 맞춰 가라"는 문장을 넣었습니다.

## 3. 근거

### 속도 [확인]
- 영어의 전형적 말하기 속도는 약 4음절/초(범위 3.3~5.9): https://en.wikipedia.org/wiki/Speech_tempo
- 미국 영어 조음 속도(휴지 제외)는 연구에 따라 4.88, 5.12음절/초: https://www.researchgate.net/publication/41453242_Articulation_rate_across_dialect_age_and_gender
- 지시문에는 "4 to 5 syllables per second"로 썼습니다. Live 모델이 숫자를 얼마나 지키는지는 근거가 없어 귀로 확인해야 합니다. [미확인]

### 덩어리(억양 단위) [확인]
- 즉흥 발화의 억양 단위는 보통 4단어 안팎이고 한 번에 새 생각 하나를 담습니다: https://languagelog.ldc.upenn.edu/myl/Chafe1994IntonationUnits.pdf
- 전사 규약도 영어 억양 단위를 약 4~5단어로 봅니다: https://www.uni-saarland.de/fileadmin/upload/lehrstuhl/gergel/downloads/trans_conv.pdf
- 지시문에는 "3 to 6 words, one idea at a time"으로 썼습니다.

### 턴 사이 간격 [확인]
- 화자 교대 간격의 최빈값은 0~200 ms입니다: https://pmc.ncbi.nlm.nih.gov/articles/PMC2705608/ , https://staff.fnwi.uva.nl/r.fernandezrovira/teaching/cosp/cosp2016/docs/HeldnerEdlund2010.pdf
- 반응 시점은 서버의 끝점 감지(VAD) 설정이 더 크게 좌우하므로 지시문만으로는 조정하지 못합니다.

### 필러와 담화 표지 [확인 + 일부 미확인]
- uh는 작은 지연, um은 큰 지연의 예고입니다(Clark & Fox Tree 2002): https://pubmed.ncbi.nlm.nih.gov/12062148/
- 필러는 채움 휴지(uh, um)와 담화 표지(I mean, you know, like) 두 묶음이며 개인차가 큽니다: https://journals.sagepub.com/doi/10.1177/0261927X14526993
- 정확한 빈도 수치는 확인하지 못했습니다. [미확인] 그래서 "3~4턴에 한 번"처럼 보수적으로 썼습니다. 많이 쓰면 연기처럼 들립니다.

### 백채널 [확인]
- mmhm/uhhuh 46%, yeah 27%, right 9%: https://www.cs.columbia.edu/nlp/papers/2007/benus_al_07b.pdf
- 백채널은 화자 교대 없이 "듣고 있다"를 알리는 짧은 반응입니다: https://en.wikipedia.org/wiki/Backchannel_(linguistics)

### 자기 수정, 축약, 흐려지는 끝맺음 [미확인, 일반 상식]
- gonna, wanna, gotta, kinda, 'cause, dunno는 격식 없는 대화에서 사실상 기본값입니다. 재시작("I was- I mean")과 꼬리("so yeah...")도 흔합니다.

### Gemini Live 조종 수단 [확인]
- 시스템 지시문은 "페르소나, 대화 규칙, 가드레일" 순서로 짜고, 억양은 출력 언어와 함께 지정합니다: https://ai.google.dev/gemini-api/docs/live-api/best-practices
- 목소리는 `speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName`으로 고릅니다: https://ai.google.dev/gemini-api/docs/live-api/capabilities
- TTS식 보컬 태그를 Live에서 쓸 수 있다는 보장은 없습니다: https://ai.google.dev/gemini-api/docs/speech-generation
- 그래서 조종 수단은 (a) 영어로 쓴 구체적 말투 지시, (b) 목소리, (c) "General American" 억양 지정, 세 가지입니다.

## 4. 기술 결정

1. 공통 말투 블록은 `partnerPrefix`에서 한 번만 넣습니다. 이유: 일곱 곳에 복사하면 고칠 때 어긋납니다. 틀리면 드는 비용: 친구별로 다른 말투를 원할 때 블록을 쪼개야 합니다.
2. 문자 채팅에는 넣지 않습니다. 이유: 필러, 말줄임, 4~5음절/초는 소리 전용입니다. 틀리면 드는 비용: 채팅이 글 같아 보일 수 있고, 그때는 `TEXTING STYLE`을 고칩니다.
3. 느린 말투(Lukas, Carmen)를 보통 속도로 올렸습니다. 이유: 사용자가 진짜 속도를 원합니다. 틀리면 드는 비용: 초급 학습자가 못 따라가면 지시문의 "easier words" 규칙에 기댑니다.
4. `PARTNER_PROMPT_LIMIT`(26000)은 그대로 둡니다. 이유: 블록 추가 후에도 가장 긴 Brian이 약 21.8k자입니다.
