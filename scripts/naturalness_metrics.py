"""대화 자연스러움 시험(scripts/naturalness_qa.py)이 쓰는 순수 지표 함수.

소리·전문·시각 목록을 받아 숫자와 판정만 돌려준다. 네트워크·파일·시계를 만지지 않으므로 단위 시험으로 고정한다.
시각은 모두 통화 시작(내 마이크 첫 프레임)부터 센 초다. 기준값은 Sesame 통화 한 건의 측정(sesame-metrics.md)에서 왔고,
한 건짜리 표본이라 일반화는 [미확인]이다.
"""
from __future__ import annotations

import re
import statistics
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

FRAME_S = 0.02
SPEECH_DB = -50.0  # 이보다 큰 20 ms 프레임을 소리로 본다(전달받은 소리의 디지털 무음은 -180 dB).

Segment = Tuple[float, float]

# 판정 기준 (낮은 값, 높은 값). None이면 그쪽은 제한이 없다.
THRESHOLDS: Dict[str, Tuple[Optional[float], Optional[float]]] = {
    "gap_ms": (800, 2000),  # Sesame: 사용자 끝 → Maya 시작 중앙 1190 ms, p90 1970 ms, 500 ms 미만 즉답은 드묾
    "gap_after_backchannel_ms": (800, 3000),  # Sesame: 반응어 뒤 다음 발화까지 중앙 1.8 s
    "median_gap_ms": (600, 2000),
    "max_gap_ms": (None, 3000),
    "false_starts": (0, 0),  # Sesame: 사용자 휴지 26회(최대 3.27 s) 모두 기다림
    "stop_latency_ms": (None, 1000),  # Sesame: 끼어들면 중앙 630 ms 안에 멈춤
    "reengage_s": (9.0, 14.0),  # Sesame에 긴 침묵 표본이 없다 [미확인]. 사용자 P4 사양 10 s: 서버 타이머 10 s + 모델 첫 소리 1~2 s + 측정 여유.
    "words_per_turn_median": (10, 45),  # Sesame: 턴 길이 중앙 17.5 단어, p90 65.5
    "question_rate": (None, 0.5),  # Sesame: 48턴 중 9턴(19%)이 질문으로 끝남
    "statement_words": (8, None),  # 짧은 대답 뒤 평서문으로 자기 이야기를 얹은 단어 수
}


def in_range(value: Optional[float], key: str) -> bool:
    """THRESHOLDS[key] 범위 안이면 True. 값이 없으면 False."""
    if value is None:
        return False
    low, high = THRESHOLDS[key]
    return (low is None or value >= low) and (high is None or value <= high)


def frame_db(samples, sample_rate: int, frame_s: float = FRAME_S) -> List[float]:
    """샘플을 frame_s 길이 프레임으로 나눠 프레임별 RMS를 dBFS로 돌려준다(정수형은 32768로 나눈다)."""
    import numpy as np

    arr = np.asarray(samples)
    x = arr.astype(np.float32) / 32768.0 if arr.dtype.kind in "iu" else arr.astype(np.float32)
    size = max(1, int(round(sample_rate * frame_s)))
    count = len(x) // size
    if count == 0:
        return []
    rms = np.sqrt((x[: count * size].reshape(count, size) ** 2).mean(axis=1))
    return [float(v) for v in 20.0 * np.log10(rms + 1e-9)]


def speech_segments(
    db: Sequence[float],
    frame_s: float = FRAME_S,
    threshold_db: float = SPEECH_DB,
    min_speech_s: float = 0.12,
    merge_gap_s: float = 0.3,
) -> List[Segment]:
    """프레임별 dB에서 소리 구간 (시작, 끝) 목록. merge_gap_s 이하 틈은 이어 붙이고 min_speech_s보다 짧은 구간은 버린다."""
    runs: List[List[float]] = []
    start: Optional[int] = None
    for i, value in enumerate(db):
        if value > threshold_db:
            if start is None:
                start = i
        elif start is not None:
            runs.append([start * frame_s, i * frame_s])
            start = None
    if start is not None:
        runs.append([start * frame_s, len(db) * frame_s])
    merged: List[List[float]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= merge_gap_s + 1e-9:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    return [(round(s, 3), round(e, 3)) for s, e in merged if e - s >= min_speech_s - 1e-9]


def leading_speech(db: Sequence[float], frame_s: float = FRAME_S, gap_s: float = 0.1, drop_db: float = 35.0) -> Optional[Segment]:
    """클립 맨 앞 첫 소리 덩어리(첫 낱말)의 (시작, 끝). 클립 최대치보다 drop_db 낮은 것을 무음으로 본다."""
    if not db:
        return None
    segs = speech_segments(db, frame_s, threshold_db=max(db) - drop_db, min_speech_s=0.05, merge_gap_s=gap_s)
    return segs[0] if segs else None


def speech_bounds(db: Sequence[float], frame_s: float = FRAME_S) -> Optional[Segment]:
    """클립에서 말이 시작하고 끝나는 시각. 클립 최대치보다 35 dB 낮은 것을 무음으로 본다."""
    if not db:
        return None
    segs = speech_segments(db, frame_s, threshold_db=max(db) - 35.0, min_speech_s=0.05, merge_gap_s=0.25)
    return (segs[0][0], segs[-1][1]) if segs else None


def segment_containing(segs: Iterable[Segment], t: float, tol: float = 0.0) -> Optional[Segment]:
    for s, e in segs:
        if s - tol <= t < e + tol:
            return (s, e)
    return None


def response_gap_ms(learner_end: float, partner_segs: Sequence[Segment]) -> Optional[int]:
    """학습자 말 끝 → 파트너가 그 뒤에 이어 말한 첫 구간의 시작까지, ms. 말 위로 시작했으면 음수. 없으면 None.

    학습자 말 끝 이후까지 이어지는 첫 구간을 고르므로, 그 전에 끝난 인사 구간은 세지 않는다."""
    for s, e in partner_segs:
        if e > learner_end:
            return int(round((s - learner_end) * 1000))
    return None


def pause_false_starts(pause_start: float, pause_end: float, partner_segs: Sequence[Segment]) -> List[float]:
    """학습자가 문장 중간에서 쉬는 동안(pause_start, pause_end) 파트너가 새로 말을 시작한 시각들."""
    return [s for s, _ in partner_segs if pause_start < s < pause_end]


def stop_latency(partner_segs: Sequence[Segment], barge_t: float, limit_s: float = 6.0) -> Dict[str, object]:
    """학습자가 barge_t에 끼어들었을 때 파트너가 멈추기까지 걸린 시간.

    status: stopped(latency_s 있음) | no_stop(limit_s 안에 안 멈춤) | not_speaking(그 시각에 파트너가 말하지 않음 → 시험 무효)."""
    seg = segment_containing(partner_segs, barge_t)
    if seg is None:
        return {"status": "not_speaking", "latency_s": None, "segment": None}
    latency = seg[1] - barge_t
    if latency > limit_s:
        return {"status": "no_stop", "latency_s": None, "segment": seg}
    return {"status": "stopped", "latency_s": round(latency, 3), "segment": seg}


def backchannel_outcome(
    partner_segs: Sequence[Segment], bc_start: float, bc_end: float, hold_s: float = 1.0
) -> Dict[str, object]:
    """파트너가 말하는 중간에 학습자가 짧은 맞장구를 했을 때의 결과.

    kept_going: 맞장구가 끝난 뒤 hold_s 이상 말이 이어짐 | stopped: 그 전에 멈춤 | invalid: 맞장구 시각에 파트너가 말하지 않음."""
    seg = segment_containing(partner_segs, bc_start, tol=0.05)
    if seg is None:
        return {"status": "invalid", "stopped_after_s": None, "next_onset_s": None}
    if seg[1] >= bc_end + hold_s:
        return {"status": "kept_going", "stopped_after_s": None, "next_onset_s": None}
    nxt = next((s for s, _ in partner_segs if s > seg[1]), None)
    return {
        "status": "stopped",
        "stopped_after_s": round(seg[1] - bc_start, 3),
        "next_onset_s": None if nxt is None else round(nxt - seg[1], 3),
    }


def reengage_seconds(partner_segs: Sequence[Segment], partner_end: float, horizon_s: float) -> Optional[float]:
    """파트너 말이 끝난 뒤 학습자가 침묵했을 때, 파트너가 다시 말을 꺼내기까지 초. horizon_s 안에 없으면 None."""
    for s, _ in partner_segs:
        if s > partner_end + 0.05:
            wait = s - partner_end
            return round(wait, 3) if wait <= horizon_s else None
    return None


# ---- 글 지표 ----

_WORD_RE = re.compile(r"[A-Za-z0-9가-힣]+(?:['’][A-Za-z]+)?")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_TURN_LINE_RE = re.compile(r"^\*\*(Me|Partner):\*\*[ \t]*(.*)$", re.MULTILINE)


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def ends_with_question(text: str) -> bool:
    return (text or "").rstrip(" \t\n\"'”’)*_").endswith("?")


def statement_words(text: str) -> int:
    """질문이 아닌 문장에 들어 있는 단어 수. 파트너가 질문 말고 자기 내용을 얼마나 말했는지 본다."""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split((text or "").strip()) if s.strip()]
    return sum(count_words(s) for s in sentences if not ends_with_question(s))


def parse_transcript(markdown: str) -> List[Tuple[str, str]]:
    """저장된 통화 전문에서 (화자, 글) 목록. 화자는 Me | Partner."""
    return [(m.group(1), m.group(2).strip()) for m in _TURN_LINE_RE.finditer(markdown or "")]


def partner_turn_stats(turns: Sequence[Tuple[str, str]]) -> Dict[str, object]:
    """파트너 턴의 단어 수 중앙값과 질문으로 끝난 턴의 비율."""
    texts = [t for who, t in turns if who == "Partner" and t.strip()]
    if not texts:
        return {"turns": 0, "words_median": None, "question_rate": None, "words": []}
    words = [count_words(t) for t in texts]
    questions = sum(1 for t in texts if ends_with_question(t))
    return {
        "turns": len(texts),
        "words_median": statistics.median(words),
        "question_rate": round(questions / len(texts), 3),
        "words": words,
    }


def median_or_none(values: Sequence[float]) -> Optional[float]:
    return statistics.median(values) if values else None


# ---- 묶음 4 판정 (P2 pause_intrusions, P4 reengage_kind, P5 yeah_followup, P1 barge_heard) ----

WAIT_SIGNAL_MAX_WORDS = 5  # 사용자 P2: 짧은 기다림 신호 "대략 5단어 이하". 완화하려면 이 상수 하나.
WAIT_SIGNAL_MAX_DUR_S = 2.0
WAIT_SIGNAL_SILENT_MAX_DUR_S = 1.0  # 글 없이 소리만 있을 때 mm-hm류로 인정하는 최대 길이

BACKCHANNEL_WORDS = frozenset({"yeah", "yep", "mm", "hm", "mmhm", "mhm", "huh", "uh", "right", "oh", "okay", "ok", "sure"})
WAIT_LEXICON = frozenset(
    "take your time no rush worries hurry i'm im i am listening here go on ahead okay ok sure yeah yep mm mmhm mm-hm hmm "
    "hm huh uh-huh uh right whenever you're youre you ready all good fine got it alright cool totally still with think "
    "thinking about that's thats slowly easy sorry".split()
) | BACKCHANNEL_WORDS
STOPWORDS = frozenset(
    "a an the and or but so to of in on at for with from by as is are was were be been it its this that these those i you he "
    "she we they me my your our their him her them do does did have has had not no yes can could would should will just "
    "like then than too very really if when what which who how why".split()
)

_PRESENCE_RE = re.compile(
    r"are you (still )?there|you there\b|still there|can you hear|hello\?|you still with me|did i lose you|"
    r"everything (ok|okay|alright)|you (ok|okay|alright)\?",
    re.IGNORECASE,
)


def word_tokens(text: str) -> List[str]:
    """소문자 낱말 목록(곡선 따옴표는 곧은 따옴표로 바꾼다)."""
    return [w.lower() for w in _WORD_RE.findall((text or "").replace("\u2019", "'"))]


def content_words(text: str) -> frozenset:
    """불용어와 기다림 어휘를 뺀 내용 낱말 집합."""
    return frozenset(w for w in word_tokens(text) if w not in STOPWORDS and w not in WAIT_LEXICON)


def _shares_two_word_chain(rest_text: str, text: str) -> bool:
    rest, said = word_tokens(rest_text), word_tokens(text)
    said_pairs = {(a, b) for a, b in zip(said, said[1:])}
    return any((a, b) in said_pairs and not (a in STOPWORDS and b in STOPWORDS) for a, b in zip(rest, rest[1:]))


def pause_intrusions(
    p0: float,
    p1: float,
    partner_segs: Sequence[Segment],
    bot_texts: Sequence[Tuple[float, str]],
    rest_words: Iterable[str] = (),
    rest_text: str = "",
) -> Dict[str, object]:
    """학습자가 문장 중간에서 쉬는 구간 [p0, p1] 안의 파트너 끼어듦 판정(설계 H4).

    짧은 기다림 신호(WAIT_SIGNAL_MAX_WORDS 낱말 이하, 같은 화제, 질문 아님, 한 번)는 PASS, 나머지는 FAIL.
    결과 kind: waited | wait_signal | multiple | question | finished_sentence | long | unverifiable | off_topic."""
    onsets = [(s, e) for s, e in partner_segs if p0 < s < p1]
    if not onsets:
        return {"verdict": "PASS", "kind": "waited", "text": "", "dur": 0.0, "onset": None}
    if len(onsets) >= 2:
        return {"verdict": "FAIL", "kind": "multiple", "text": "", "dur": 0.0, "onset": onsets[0][0]}
    s, e = onsets[0]
    dur = round(e - s, 3)
    next_on = next((ns for ns, _ in partner_segs if ns > s), float("inf"))
    upper = min(e + 1.0, next_on - 0.1)
    text = " ".join(" ".join(t for ts, t in bot_texts if s - 0.5 <= ts <= upper).split())
    words = count_words(text)

    def result(verdict: str, kind: str) -> Dict[str, object]:
        return {"verdict": verdict, "kind": kind, "text": text, "dur": dur, "onset": s}

    if "?" in text:
        return result("FAIL", "question")
    if len(content_words(text) & frozenset(rest_words)) >= 2 or (rest_text and _shares_two_word_chain(rest_text, text)):
        return result("FAIL", "finished_sentence")
    if words > WAIT_SIGNAL_MAX_WORDS or dur > WAIT_SIGNAL_MAX_DUR_S:
        return result("FAIL", "long")
    if e > p1 + 0.3:
        return result("FAIL", "long")
    if not text:
        return result("PASS", "wait_signal") if dur <= WAIT_SIGNAL_SILENT_MAX_DUR_S else result("FAIL", "unverifiable")
    if all(w in WAIT_LEXICON for w in word_tokens(text)):
        return result("PASS", "wait_signal")
    return result("FAIL", "off_topic")


STORY_MIN_WORDS = 8
BARGE_CONTENT_WORDS = ("limit", "time", "conversation", "have")


def yeah_followup(reply: str, partner_spoke: bool = True) -> Dict[str, object]:
    """"Yeah"만 들은 파트너 답의 분류(설계 H5). PASS는 story뿐이다.

    no_reply(글도 소리도 없음) | unverifiable(소리는 있으나 글 없음) | question_only(질문 아닌 문장 단어 < 8)
    | question_first(길어도 첫 문장이 질문) | story_then_question(길고 마지막 문장이 질문) | story."""
    reply = (reply or "").strip()
    if not reply:
        return {"kind": "unverifiable" if partner_spoke else "no_reply", "statement_words": None}
    words = statement_words(reply)
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(reply) if s.strip()]
    if words < STORY_MIN_WORDS:
        kind = "question_only"
    elif ends_with_question(sentences[0]):
        kind = "question_first"
    elif ends_with_question(sentences[-1]):
        kind = "story_then_question"
    else:
        kind = "story"
    return {"kind": kind, "statement_words": words}


def reengage_kind(text: str) -> str:
    """침묵 뒤 파트너가 꺼낸 말의 종류(설계 H3): content | presence_check | question | none.

    none은 말이 없거나 질문도 아니고 내용(질문 아닌 문장 6단어 이상)도 못 되는 짧은 말이다."""
    text = (text or "").strip()
    if not text:
        return "none"
    if _PRESENCE_RE.search(text):
        return "presence_check"
    words = statement_words(text)
    if words < 6 and ends_with_question(text):
        return "question"
    return "content" if words >= 6 else "none"


def barge_heard(turns: Sequence[Tuple[str, str]], words: Sequence[str] = BARGE_CONTENT_WORDS) -> Dict[str, object]:
    """끼어든 문장을 파트너가 들었는지(설계 H6). 전문의 Me 턴에 내용 낱말이 2개 이상 있고 그 뒤에 파트너 턴이 있으면 PASS."""
    for i, (who, text) in enumerate(turns):
        if who != "Me":
            continue
        found = sorted({w for w in word_tokens(text) if w in words})
        if len(found) >= 2 and any(w == "Partner" for w, _ in turns[i + 1:]):
            return {"verdict": "PASS", "words": found}
    return {"verdict": "FAIL", "words": []}
