"""학습자 전사에서 한자·가나를 정리한다.

Gemini Live의 입력 전사는 언어 힌트가 없으면 짧은 추임새("음", "으흠")를 중국어로 분류해
"嗯"처럼 낸다. 화면 자막과 저장 전문이 그대로 오염되지 않게 같은 규칙으로 걸러 낸다.
같은 규칙이 src/lib/transcript.ts에 있고 두 시험이 같은 입력표를 쓴다.
"""

import re

# 한자(통합·확장 A·호환)와 일본어 가나. 한글과 라틴 글자는 포함하지 않는다.
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
# 이 글자가 하나라도 남으면 "섞여 있다"고 본다(한글 자모·라틴·숫자).
_KEEP_RE = re.compile(r"[A-Za-z0-9\u00c0-\u024f\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
SHORT_LIMIT = 12


def clean_learner_text(text: str) -> str:
    """한자·가나만 있으면 (mm)/(unclear)로, 다른 글자와 섞여 있으면 한자·가나만 지운다."""
    if not text or not _CJK_RE.search(text):
        return text
    if not _KEEP_RE.search(text):
        return "(mm)" if len("".join(text.split())) <= SHORT_LIMIT else "(unclear)"
    return " ".join(_CJK_RE.sub(" ", text).split())
