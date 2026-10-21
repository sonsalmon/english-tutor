#!/usr/bin/env python3
"""원어민 표현 목록을 만든다: 자막 DB에서 후보를 모으고, agy(Gemini)로 판정하고, 순위와 클립을 붙인다.

세 단계이고 각각 이어서 다시 돌려도 된다(결과 파일이 있으면 건너뛴다).
  candidates  tv·podcast·work 채널 자막의 2~5낱말 덩어리(빈도·연관도)와 내장 시드 목록에서 후보 약 1,500개를 고른다.
  judge       후보를 40개씩 agy로 보내 non_compositional·kind·뜻·어려운 이유를 JSON으로 받는다(배치마다 파일로 저장).
  finalize    non_compositional이고 literal이 아닌 것만 남겨 원어민 빈도(백만 낱말당)로 순위를 매기고 표현마다 실제 클립을 최대 3개 붙인다.
자막 DB는 읽기 전용으로만 연다. 결과는 --work-dir·--out에만 쓰고, 학습 폴더(~/dev/learning/english)에는 쓰지 않는다.
"""

import argparse
import functools
import json
import math
import random
import re
import subprocess
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import clipdb, native_expr  # noqa: E402

DEFAULT_WORK_DIR = Path.home() / "dev" / ".omo" / "dag" / "next12" / "t7-work"
DEFAULT_OUT = Path.home() / "dev" / ".omo" / "dag" / "next12" / "native-expressions.json"
LEARNING_DIR = Path.home() / "dev" / "learning" / "english"
SOURCE_GENRES = ("tv", "podcast", "work")
MODEL = "gemini-4-argon-medium"
FALLBACK_MODEL = "gemini-3.8-flash-medium"

MAX_N = 5
MIN_COUNT = 8
MIN_SEED_COUNT = 3
MIN_PMI = 3.0
PRE_LIMIT = 5000
CANDIDATE_LIMIT = 1500
MIN_VIDEOS = 5
MIN_CHANNELS = 2
BATCH_SIZE = 40
FINAL_MAX = 600
CLIPS_PER_EXPRESSION = 3
CLIP_POOL = 40
KINDS = ("idiom", "phrasal_verb", "chunk", "discourse_marker")
ALL_KINDS = KINDS + ("literal",)
REGISTERS = ("casual", "neutral", "work")
EXIT_OK, EXIT_FATAL, EXIT_QUOTA = 0, 1, 3

STOPWORDS = frozenset(
    """a about after again all also am an and any are aren't as at be because been before being both but by can can't
    could couldn't did didn't do does doesn't doing don't down for from further get gets got gonna gotta had has hasn't have
    haven't having he her here hers him his how i i'd i'll i'm i've if in into is isn't it it's its just me more most my no
    nor not now of off on once only or other our out over own same she should so some such than that that's the their them
    then there there's these they they're this those through to too under until up us very wanna was wasn't we we're were
    weren't what when where which while who whom why will with won't would wouldn't you you'd you'll you're you've your
    yours um uh oh okay ok yeah yes hey hmm mm like really actually just well""".split()
)
START_BAD = frozenset("and but or the a an of is are was were to that so if".split())
END_BAD = frozenset(
    """the a an and or but of to is are was were i you he she it we they my your that this in on at for with as be
    by from his her their our its""".split()
)

SEEDS = """
figure out | end up | come up with | work out | find out | give up | look forward to | put up with | run out of
get along with | get over | get away with | take over | take off | take on | turn out | turn down | turn up | pick up
pass out | show up | set up | break down | break up | bring up | bring about | call off | carry on | carry out | catch up
check out | cheer up | come across | come over | come through | cut off | deal with | drop off | fall apart | fall for
fill in | get back to | get through | give in | go ahead | go over | go through | grow up | hang out | hold on | hold back
keep up | kick off | let down | look into | look up to | look out | make up | make out | mess up | miss out | move on
point out | pull off | put off | put together | reach out | rule out | run into | sort out | stand out | stand for
stand up for | step up | stick to | take care of | take advantage of | think over | throw up | try out | turn into | wind up
wrap up | walk through | zone out | back up | back off | blow up | bring in | burn out | buy into | chip in | clean up
come back to | come down to | count on | cut back | dive into | dig into | drag on | dress up | drop by | end up with
face up to | fit in | follow up | get ahead | get by | get into | get on with | give back | go on | hang on | hang up
head out | hit up | hold up | iron out | jump in | keep on | knock out | lay off | lean on | level up | line up | log in
look after | make it | make up for | mix up | open up | opt out | pay off | phase out | pile up | plug in | pop up | pull up
push back | put forward | reach out to | roll out | run by | run through | scale up | see through | sell out | send out
settle down | shut down | sign up | slow down | speak up | start over | stay up | step down | stop by | sum up | take in
take out | take up | talk into | talk over | tell apart | tone down | touch on | track down | turn around
turn out to be | use up | watch out | weigh in | work on | work through | write off | come on | come out | come in | come up
go out | go off | get up | get out | get off | get back | get together | give away | hand in | hand out | hold off
let go | look at | look for | make do | play around | pull out | put away | put in | put on | run away | set off
set out | show off | shut up | sit down | stay out | take back | take down | turn on | turn off | wake up | work up
call it a day | no big deal | touch base | piece of cake | under the weather | break the ice | hit the nail on the head
bite the bullet | cost an arm and a leg | spill the beans | let the cat out of the bag | once in a blue moon
the last straw | on the same page | in the loop | out of the blue | behind the scenes | at the end of the day
back to square one | the ball is in your court | by the book | cut corners | get the ball rolling | go the extra mile
hit the ground running | in the long run | on the fence | on top of it | over the moon | pull my leg | rule of thumb
see eye to eye | sleep on it | speak of the devil | take it easy | take it with a grain of salt | throw in the towel
up in the air | water under the bridge | a blessing in disguise | add insult to injury | beat around the bush
burn the midnight oil | burn bridges | caught off guard | cross that bridge when we come to it | cut it out
easier said than done | every now and then | face the music | get cold feet | give it a shot
go back to the drawing board | hang in there | have a blast | hit the road | hit the sack | in a nutshell | keep an eye on
keep in mind | keep your fingers crossed | kill two birds with one stone | let it go | make ends meet
make a long story short | miss the boat | no brainer | not my cup of tea | off the top of my head | on the spot
out of hand | play it by ear | put your foot down | rain check | read between the lines | rub me the wrong way
run out of steam | save face | second thoughts | shoot yourself in the foot | sit tight | steal the show
stick your neck out | take for granted | the whole nine yards | think outside the box | through thick and thin
tip of the iceberg | under the radar | up to speed | walk on eggshells | wrap your head around | you name it
bend over backwards | bring to the table | call the shots | cut to the chase | drop the ball | get the hang of it
give me a heads up | go with the flow | have a lot on my plate | hold your horses | jump the gun | keep it up
learn the ropes | look on the bright side | lose track of time | make sense | on the fly | pull an all nighter
push the envelope | put on hold | ring a bell | run the show | split the bill | stay on top of | take a rain check
turn a blind eye | up for grabs | word of mouth | a heads up | ballpark figure | big deal | long shot | no way | my bad
you bet | no worries | fair enough | give me a break | what's up | how come | what the heck | for real | no kidding
count me in | you got this | sounds good | works for me | hang tight | bear with me | heads up | fingers crossed
long story short | to be honest | to be fair | the thing is | as a matter of fact | by the way | in the meantime | i mean
you know | kind of | sort of | a lot of | i guess | i suppose | you know what | you know what i mean | if you will
so to speak | for what it's worth | to tell you the truth | believe it or not | as far as i know
as far as i'm concerned | the point is | having said that | that being said | all things considered
on the other hand | then again | in other words | for the most part | for instance | not to mention | needless to say
come to think of it | speaking of | when it comes to | in terms of | with regard to | as well as | as soon as
as long as | no matter what | no matter how | sooner or later | more or less | once and for all | all of a sudden
by all means | by any chance | at least | at all | in fact | of course | right now | right away | pretty much
just in case | on purpose | by accident | in a row | so far | so what | what if | how about | why not
i'm not sure | i don't think so | i can't believe | i'm just saying | what do you mean | tell me about it
you're kidding | you got it | that makes sense | that's the thing | it depends | it turns out | turns out
it's not like | i wish i could | how's it going | what have you been up to | what's going on | long time no see
same here | me neither | take care | see you around | catch you later | good for you | good luck with that
i'm all ears | i'm on it | i'm down | i'm over it | get over it | get a life | get real | get lost
get out of here | get this | guess what | mind you | mark my words | believe me | trust me | no offense
don't get me wrong | hear me out | let me know | let's face it | let's see | you see | i hear you | got it
my pleasure | don't mention it | not at all | thank god | oh my god | holy cow | thank goodness
for god's sake | what the hell | are you serious | the fact that | in my opinion | at the moment | in the end
at some point | to some extent | a couple of | a bunch of | a little bit | a few | kind of like | sort of like
i don't know | i don't care | i don't mind | i have no idea | i have to say | i have a feeling | you have to
you've got to | you'd better | had better | would rather | used to | be used to | get used to | be about to
be supposed to | be going to | be able to | be willing to | have got to | ought to | in charge of | in favor of
in front of | on behalf of | on top of | out of | because of | instead of | in addition to | due to | thanks to
according to | regardless of | rather than | other than | apart from | aside from | more than | less than
as if | as though | even if | even though | whether or not | not only | either way | one way or another
by far | for sure | for good | for now | for ever | in general | in particular | in person | in public | in private
on and on | over and over | again and again | back and forth | up and down | more and more | little by little
step by step | one by one | side by side | day by day | face to face | hand in hand | here and there
"""

PROMPT_HEAD = """You are a linguist who helps Korean learners of American English.
For each numbered item decide whether it is a NATIVE-ONLY EXPRESSION: a learner who knows the dictionary meaning of every single word still cannot work out its meaning or its natural use. Be strict.

non_compositional = true only for:
- idiom (kick the bucket, call it a day)
- phrasal_verb whose meaning is not literal (figure out, end up, come up with, put up with)
- chunk: a fixed set phrase natives use as one unit whose meaning or use a learner would not build from the words (no big deal, you bet, long story short)
- discourse_marker: a phrase that manages the conversation rather than adding content (the thing is, to be fair, I mean)
Hedges and fillers such as "you know", "I mean", "kind of", "sort of" count as discourse_marker even though every word is common, because their job in speech is not in the dictionary meanings. Short verb chunks whose usual meaning is idiomatic ("get it" = understand, "make it" = succeed or arrive in time) count too.
non_compositional = false, kind = "literal", for literal word combinations (talk about, go to the store), names, cut-off fragments, and anything a learner could build and understand word by word.

Fields per item (all required):
- id: the item number
- expression: the expression in its natural base form (fix a cut-off fragment only if the intended expression is obvious, otherwise mark literal)
- non_compositional: true or false
- kind: idiom | phrasal_verb | chunk | discourse_marker | literal
- meaning_ko: the usual meaning in Korean (most common sense first, comma separated), at most 20 characters
- why_hard_for_korean: ONE Korean sentence that names the concrete trap for a Korean speaker (for example which word's dictionary meaning misleads, or which Korean phrase it does not match). No generic advice such as "practice a lot".
- register: casual | neutral | work
- example: one natural, short American English sentence (at most 14 words) using the expression
For literal items write short placeholders: meaning_ko "", why_hard_for_korean "", example "".

Reply with ONLY a JSON array with one object per item, in the same order. No markdown, no commentary. Do not use any tools and do not read or write any files.

Items:
"""

QUOTA_RE = re.compile(r"quota|rate.?limit|resource.?exhausted|too many requests|\b429\b|exceeded", re.IGNORECASE)


class QuotaError(Exception):
    pass


class StopPipeline(Exception):
    pass


@functools.lru_cache(maxsize=None)
def lemma(word: str) -> str:
    return sys.intern(native_expr.lemma_token(word))


def lemmas(text: str) -> List[str]:
    return [lemma(t) for t in native_expr.tokens(text)]


def seed_keys() -> List[Tuple[str, ...]]:
    """내장 시드 목록을 원형 낱말 튜플로 바꾼다(중복 제거, 한 낱말짜리와 6낱말 이상은 뺀다)."""
    seen: set = set()
    keys: List[Tuple[str, ...]] = []
    for raw in re.split(r"\||\n", SEEDS):
        parts = tuple(lemmas(raw))
        if 2 <= len(parts) <= MAX_N and parts not in seen:
            seen.add(parts)
            keys.append(parts)
    return keys


def refuse_learning_dir(path: Path) -> None:
    resolved = Path(path).expanduser().resolve()
    if resolved == LEARNING_DIR.resolve() or LEARNING_DIR.resolve() in resolved.parents:
        raise SystemExit(f"학습 폴더에는 쓰지 않습니다: {resolved}")


def iter_segments(db: Path, genres: Sequence[str] = SOURCE_GENRES) -> Iterator[Dict[str, Any]]:
    """tv·podcast·work 채널의 자막 세그먼트. 자막 DB는 읽기 전용으로만 연다."""
    marks = ",".join("?" for _ in genres)
    sql = (
        'SELECT s.video_id AS video_id, s.start AS start, s."end" AS "end", s.text AS text, '
        "v.title AS title, c.title AS channel, c.handle AS handle, c.genre AS genre "
        "FROM segments s JOIN videos v ON v.id = s.video_id "
        "JOIN channels c ON c.handle = v.channel_handle "
        f"WHERE v.status = 'ok' AND c.genre IN ({marks})"
    )
    conn = clipdb._open_ro(Path(db))
    try:
        for row in conn.execute(sql, list(genres)):
            yield dict(row)
    finally:
        conn.close()


def is_noise(gram: Tuple[str, ...]) -> bool:
    """불용어만으로 된 덩어리, 가장자리가 기능어인 덩어리, 같은 낱말 반복, 한 글자 낱말을 가진 덩어리."""
    if all(t in STOPWORDS for t in gram):
        return True
    if gram[0] in START_BAD or gram[-1] in END_BAD:
        return True
    if any(a == b for a, b in zip(gram, gram[1:])):
        return True
    return any(len(t) == 1 and t not in ("i", "a") for t in gram)


def count_ngrams(
    docs: Sequence[Sequence[str]], seeds: Iterable[Tuple[str, ...]], min_count: int = MIN_COUNT, max_n: int = MAX_N
) -> Dict[int, Counter]:
    """n=1..max_n 빈도. n>=3은 앞 (n-1)낱말이 min_count 이상이거나 시드인 덩어리만 센다(apriori)."""
    seed_set = set(seeds)
    counts: Dict[int, Counter] = {1: Counter(t for d in docs for t in d)}
    frequent: set = set()
    for n in range(2, max_n + 1):
        level: Counter = Counter()
        for d in docs:
            for i in range(len(d) - n + 1):
                gram = tuple(d[i : i + n])
                if n == 2 or gram[:-1] in frequent or gram in seed_set:
                    level[gram] += 1
        counts[n] = level
        frequent = {g for g, c in level.items() if c >= min_count}
    return counts


def min_split_pmi(gram: Tuple[str, ...], count: int, counts: Dict[int, Counter], total: int) -> float:
    """덩어리를 둘로 쪼갠 모든 경우의 PMI 중 가장 낮은 값(낮을수록 낱말 뜻의 합에 가깝다)."""

    def occurrences(part: Tuple[str, ...]) -> int:
        found = counts[1].get(part[0]) if len(part) == 1 else counts[len(part)].get(part)
        return max(found or count, 1)

    return min(math.log2(count * total / (occurrences(gram[:k]) * occurrences(gram[k:]))) for k in range(1, len(gram)))


def score_candidates(
    counts: Dict[int, Counter],
    total: int,
    seeds: Iterable[Tuple[str, ...]],
    min_count: int = MIN_COUNT,
    min_pmi: float = MIN_PMI,
    min_seed_count: int = MIN_SEED_COUNT,
) -> List[Dict[str, Any]]:
    """빈도(count)와 연관도(PMI)로 후보를 매긴다. 시드는 불용어·가장자리 규칙과 PMI 문턱을 건너뛴다."""
    seed_set = set(seeds)
    found: List[Dict[str, Any]] = []
    for n in range(2, max(counts) + 1):
        for gram, count in counts[n].items():
            is_seed = gram in seed_set
            if is_seed and count < min_seed_count:
                continue
            if not is_seed:
                if count < min_count or is_noise(gram):
                    continue
            pmi = min_split_pmi(gram, count, counts, total)
            if not is_seed and pmi < min_pmi:
                continue
            found.append(
                {
                    "key": " ".join(gram),
                    "count": count,
                    "per_million": round(count / total * 1e6, 3),
                    "pmi": round(pmi, 3),
                    "score": round(math.log2(count) * max(pmi, 0.0), 3),
                    "seed": is_seed,
                }
            )
    found.sort(key=lambda c: (-c["score"], c["key"]))
    return found


def select_pre_candidates(scored: List[Dict[str, Any]], limit: int = PRE_LIMIT) -> List[Dict[str, Any]]:
    """시드는 모두, 나머지는 점수 순으로 limit까지."""
    seeds = [c for c in scored if c["seed"]]
    rest = [c for c in scored if not c["seed"]][: max(0, limit - len(seeds))]
    return seeds + rest


def collect_surface(
    segments: Iterable[Dict[str, Any]], keys: Iterable[str]
) -> Dict[str, Dict[str, Any]]:
    """고른 덩어리마다 실제로 쓰인 낱말 모양, 영상·채널 수, 예문 후보를 모은다."""
    wanted = {tuple(k.split()) for k in keys}
    lengths = sorted({len(k) for k in wanted})
    info: Dict[str, Dict[str, Any]] = {
        " ".join(k): {"surface": Counter(), "videos": set(), "channels": set(), "examples": []} for k in wanted
    }
    for seg in segments:
        raw = native_expr.tokens(seg["text"])
        lem = [lemma(t) for t in raw]
        for n in lengths:
            for i in range(len(lem) - n + 1):
                gram = tuple(lem[i : i + n])
                if gram not in wanted:
                    continue
                entry = info[" ".join(gram)]
                entry["surface"][" ".join(raw[i : i + n])] += 1
                entry["videos"].add(seg["video_id"])
                entry["channels"].add(seg["handle"])
                if len(entry["examples"]) < 6 and 6 <= len(raw) <= 22:
                    entry["examples"].append(seg["text"])
    return info


def display_form(surface: Counter, key: str) -> str:
    """가장 많이 쓰인 모양을 보이되, 원형 그대로의 모양이 그 25% 이상이면 원형을 쓴다."""
    if not surface:
        return key
    top, top_count = surface.most_common(1)[0]
    if surface.get(key, 0) >= 0.25 * top_count:
        return key
    return top


def build_candidates(
    segments: Sequence[Dict[str, Any]],
    limit: int = CANDIDATE_LIMIT,
    min_count: int = MIN_COUNT,
    min_videos: int = MIN_VIDEOS,
    min_channels: int = MIN_CHANNELS,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """후보 생성의 전 과정. (후보 목록, 통계)."""
    seeds = seed_keys()
    docs = [lemmas(s["text"]) for s in segments]
    total = sum(len(d) for d in docs)
    counts = count_ngrams(docs, seeds, min_count=min_count)
    pre = select_pre_candidates(score_candidates(counts, total, seeds, min_count=min_count))
    info = collect_surface(segments, [c["key"] for c in pre])
    kept: List[Dict[str, Any]] = []
    for cand in pre:
        entry = info[cand["key"]]
        dispersed = len(entry["videos"]) >= min_videos and len(entry["channels"]) >= min_channels
        if not (cand["seed"] or dispersed):
            continue
        example = min(entry["examples"], key=len) if entry["examples"] else ""
        kept.append(
            {
                **cand,
                "expression": display_form(entry["surface"], cand["key"]),
                "videos": len(entry["videos"]),
                "channels": len(entry["channels"]),
                "example": example,
            }
        )
    seed_part = [c for c in kept if c["seed"]]
    rest = [c for c in kept if not c["seed"]][: max(0, limit - len(seed_part))]
    ordered = sorted(seed_part + rest, key=lambda c: (-c["per_million"], c["key"]))
    stats = {
        "segments": len(segments),
        "tokens": total,
        "pre_candidates": len(pre),
        "after_dispersion": len(kept),
        "candidates": len(ordered),
        "seed_candidates": len(seed_part),
        "seeds_total": len(seeds),
    }
    return ordered, stats


# ---- 판정 ----


def prompt_for(batch: Sequence[Dict[str, Any]], start_id: int = 1) -> str:
    lines = []
    for offset, cand in enumerate(batch):
        example = cand.get("example") or ""
        suffix = f' (heard in: "{example}")' if example else ""
        lines.append(f'{start_id + offset}. "{cand["expression"]}"{suffix}')
    return PROMPT_HEAD + "\n".join(lines) + "\n"


def _truthy(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "yes", "y", "1"):
            return True
        if low in ("false", "no", "n", "0"):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _objects(text: str) -> Iterator[str]:
    """글 안의 최상위 {...} 조각을 차례로 낸다(문자열 안의 괄호는 무시)."""
    depth, start, in_str, escape = 0, -1, False, False
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                yield text[start : i + 1]
                start = -1


def _load_json(fragment: str) -> Any:
    try:
        return json.loads(fragment)
    except ValueError:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", fragment))


def normalize_judgement(raw: Any) -> Optional[Dict[str, Any]]:
    """판정 항목 하나를 정리한다. id가 없거나 non_compositional을 읽을 수 없으면 None."""
    if not isinstance(raw, dict):
        return None
    try:
        item_id = int(raw.get("id"))
    except (TypeError, ValueError):
        return None
    flag = _truthy(raw.get("non_compositional"))
    if flag is None:
        return None
    kind = str(raw.get("kind") or "").strip().lower().replace(" ", "_")
    if kind not in ALL_KINDS:
        kind = "literal" if not flag else ""
    register = str(raw.get("register") or "").strip().lower()
    if register not in REGISTERS:
        register = "neutral"
    text = lambda key: " ".join(str(raw.get(key) or "").split())  # noqa: E731
    return {
        "id": item_id,
        "expression": text("expression"),
        "non_compositional": flag,
        "kind": kind,
        "meaning_ko": text("meaning_ko"),
        "why_hard": text("why_hard_for_korean") or text("why_hard"),
        "register": register,
        "example": text("example"),
    }


def parse_judgement(output: str) -> List[Dict[str, Any]]:
    """모델 출력에서 판정 목록을 뽑는다. 코드 울타리·앞뒤 설명·끝 쉼표·잘린 꼬리가 있어도 읽을 수 있는 항목은 살린다."""
    text = re.sub(r"```(?:json)?", "", output or "")
    results: List[Dict[str, Any]] = []
    first, last = text.find("["), text.rfind("]")
    if 0 <= first < last:
        try:
            data = _load_json(text[first : last + 1])
            if isinstance(data, list):
                results = [r for r in (normalize_judgement(x) for x in data) if r]
        except ValueError:
            results = []
    if not results:
        for fragment in _objects(text):
            try:
                item = normalize_judgement(_load_json(fragment))
            except ValueError:
                continue
            if item:
                results.append(item)
    unique: Dict[int, Dict[str, Any]] = {}
    for item in results:
        unique.setdefault(item["id"], item)
    return [unique[k] for k in sorted(unique)]


def run_agy(prompt: str, model: str, work_dir: Path, timeout_sec: int, agy: str = "agy") -> str:
    """agy를 한 번 부른다. 한도 오류는 QuotaError, 그 밖의 실패는 RuntimeError."""
    cmd = [
        agy, "-p", prompt, "--model", model, "--dangerously-skip-permissions",
        "--add-dir", str(work_dir), "--print-timeout", f"{timeout_sec}s",
    ]
    try:
        done = subprocess.run(cmd, cwd=str(work_dir), capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout_sec + 90)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"agy 시간 초과({model})") from e
    combined = f"{done.stdout}\n{done.stderr}"
    if done.returncode != 0 or not done.stdout.strip():
        if QUOTA_RE.search(combined):
            raise QuotaError(combined.strip()[-300:])
        raise RuntimeError(f"agy 실패 rc={done.returncode} ({model}): {combined.strip()[-300:]}")
    return done.stdout


class Judge:
    """배치 판정기: 기본 모델이 한도에 걸리면 대체 모델로 넘어가고, 둘 다 걸리면 멈춘다."""

    def __init__(self, work_dir: Path, model: str, fallback: str, timeout_sec: int, runner=run_agy):
        self.work_dir, self.model, self.fallback, self.timeout_sec, self.runner = work_dir, model, fallback, timeout_sec, runner
        self.current = model
        self.lock = threading.Lock()
        self.used: Counter = Counter()

    def ask(self, prompt: str) -> str:
        for attempt in range(3):
            with self.lock:
                model = self.current
            try:
                out = self.runner(prompt, model, self.work_dir, self.timeout_sec)
            except QuotaError as e:
                with self.lock:
                    if self.current == self.model and self.fallback and self.fallback != self.model:
                        self.current = self.fallback
                        continue
                    if model == self.fallback and self.current == model:
                        raise StopPipeline(f"두 모델 모두 한도 오류: {e}") from e
                continue
            except RuntimeError:
                if attempt == 2:
                    raise
                continue
            with self.lock:
                self.used[model] += 1
            return out
        raise RuntimeError("agy 재시도 한도 초과")

    def judge_batch(self, batch: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """배치를 판정하고 항목 번호를 배치 안 순서(1부터)로 돌려준다. 빠진 항목은 한 번 더 묻는다."""
        got: Dict[int, Dict[str, Any]] = {}
        todo = list(range(1, len(batch) + 1))
        for _ in range(2):
            if not todo:
                break
            sub = [batch[i - 1] for i in todo]
            prompt = prompt_for(sub, 1)
            parsed = parse_judgement(self.ask(prompt))
            for item in parsed:
                if 1 <= item["id"] <= len(sub):
                    got[todo[item["id"] - 1]] = {**item, "id": todo[item["id"] - 1]}
            todo = [i for i in range(1, len(batch) + 1) if i not in got]
        return [got[i] for i in sorted(got)]


# ---- 마무리 ----


def keep_judged(candidate: Dict[str, Any], judged: Dict[str, Any]) -> bool:
    return bool(
        judged.get("non_compositional")
        and judged.get("kind") in KINDS
        and judged.get("meaning_ko")
        and judged.get("why_hard")
    )


def drop_contained(items: List[Dict[str, Any]], ratio: float = 0.7) -> List[Dict[str, Any]]:
    """더 긴 표현이 짧은 표현 빈도의 ratio 이상이면 짧은 쪽을 뺀다(come up / come up with)."""
    keys = [(it["key"].split(), it) for it in items]

    def inside(short: List[str], long_: List[str]) -> bool:
        n = len(short)
        return len(long_) > n and any(long_[i : i + n] == short for i in range(len(long_) - n + 1))

    drop = set()
    for short, a in keys:
        for long_, b in keys:
            if a is not b and inside(short, long_) and b["count"] >= ratio * a["count"]:
                drop.add(a["key"])
                break
    return [it for it in items if it["key"] not in drop]


def rank(items: List[Dict[str, Any]], limit: int = FINAL_MAX) -> List[Dict[str, Any]]:
    return sorted(items, key=lambda it: (-it["per_million"], it["key"]))[:limit]


def pick_clips(pool: List[Dict[str, Any]], rng: random.Random, count: int = CLIPS_PER_EXPRESSION) -> List[Dict[str, Any]]:
    """영상·채널이 겹치지 않게, 길이가 알맞은(6~18낱말, 1.5~9초) 장면을 우선해서 count개."""

    def quality(c: Dict[str, Any]) -> Tuple[int, float]:
        words = len(native_expr.tokens(c["text"]))
        duration = c["end"] - c["start"]
        good = 6 <= words <= 18 and 1.5 <= duration <= 9
        return (0 if good else 1, rng.random())

    chosen: List[Dict[str, Any]] = []
    videos: set = set()
    channels: Counter = Counter()
    for clip in sorted(pool, key=quality):
        if clip["video_id"] in videos or channels[clip["channel"]] >= 2:
            continue
        videos.add(clip["video_id"])
        channels[clip["channel"]] += 1
        chosen.append(clip)
        if len(chosen) >= count:
            break
    return chosen


def collect_clips(segments: Iterable[Dict[str, Any]], keys: Iterable[str], rng: random.Random) -> Dict[str, List[Dict[str, Any]]]:
    """표현마다 장면 후보를 CLIP_POOL개까지 무작위 표본으로 모은다(전 구간을 한 번만 훑는다)."""
    wanted = {tuple(k.split()) for k in keys}
    lengths = sorted({len(k) for k in wanted})
    pools: Dict[str, List[Dict[str, Any]]] = {" ".join(k): [] for k in wanted}
    seen_counts: Counter = Counter()
    for seg in segments:
        lem = lemmas(seg["text"])
        hit_keys = set()
        for n in lengths:
            for i in range(len(lem) - n + 1):
                gram = tuple(lem[i : i + n])
                if gram in wanted:
                    hit_keys.add(" ".join(gram))
        for key in hit_keys:
            seen_counts[key] += 1
            clip = {k: seg[k] for k in ("video_id", "start", "end", "text", "title", "channel")}
            pool = pools[key]
            if len(pool) < CLIP_POOL:
                pool.append(clip)
            else:
                j = rng.randrange(seen_counts[key])
                if j < CLIP_POOL:
                    pool[j] = clip
    return pools


def counts_by_kind(items: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    tally = Counter(it["kind"] for it in items)
    return {k: tally.get(k, 0) for k in KINDS}


# ---- 명령 ----


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def cmd_candidates(args: argparse.Namespace) -> int:
    path = args.work_dir / "candidates.json"
    if path.is_file() and not args.force:
        print(f"후보 파일이 있어 건너뜁니다: {path}")
        return EXIT_OK
    segments = list(iter_segments(args.db))
    candidates, stats = build_candidates(segments, limit=args.limit)
    write_json(path, {"stats": stats, "candidates": candidates})
    print(json.dumps(stats, ensure_ascii=False))
    return EXIT_OK


def cmd_judge(args: argparse.Namespace) -> int:
    data = json.loads((args.work_dir / "candidates.json").read_text(encoding="utf-8"))
    candidates = data["candidates"]
    batches = [candidates[i : i + args.batch_size] for i in range(0, len(candidates), args.batch_size)]
    if args.max_batches:
        batches = batches[: args.max_batches]
    judged_dir = args.work_dir / "judged"
    judged_dir.mkdir(parents=True, exist_ok=True)
    judge = Judge(args.work_dir, args.model, args.fallback_model, args.print_timeout)
    failures: List[str] = []

    def work(index: int) -> None:
        out = judged_dir / f"batch_{index:03d}.json"
        if out.is_file():
            return
        result = judge.judge_batch(batches[index])
        write_json(out, {"model": judge.current, "items": result, "expected": len(batches[index])})
        print(f"배치 {index + 1}/{len(batches)}: {len(result)}/{len(batches[index])}개 판정 ({judge.current})", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(work, i): i for i in range(len(batches))}
        for future, index in futures.items():
            try:
                future.result()
            except StopPipeline as e:
                print(f"중단: {e}", file=sys.stderr)
                pool.shutdown(wait=False, cancel_futures=True)
                return EXIT_QUOTA
            except Exception as e:  # noqa: BLE001 - 배치 하나가 실패해도 나머지를 이어서 한다
                failures.append(f"batch {index}: {e}")
    print(f"사용한 모델: {dict(judge.used)}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return EXIT_FATAL
    return EXIT_OK


def load_judgements(work_dir: Path, candidates: List[Dict[str, Any]], batch_size: int) -> List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]:
    pairs: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]] = []
    for index in range(0, len(candidates), batch_size):
        batch = candidates[index : index + batch_size]
        path = work_dir / "judged" / f"batch_{index // batch_size:03d}.json"
        by_id: Dict[int, Dict[str, Any]] = {}
        if path.is_file():
            by_id = {int(i["id"]): i for i in json.loads(path.read_text(encoding="utf-8")).get("items", [])}
        for offset, cand in enumerate(batch):
            pairs.append((cand, by_id.get(offset + 1)))
    return pairs


def cmd_finalize(args: argparse.Namespace) -> int:
    candidates = json.loads((args.work_dir / "candidates.json").read_text(encoding="utf-8"))["candidates"]
    pairs = load_judgements(args.work_dir, candidates, args.batch_size)
    judged_pairs = [(c, j) for c, j in pairs if j]
    kept: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for cand, judged in judged_pairs:
        if keep_judged(cand, judged):
            kept.append({**cand, **{k: judged[k] for k in ("kind", "meaning_ko", "why_hard", "register")}, "example": judged["example"] or cand.get("example", ""), "expression": judged["expression"] or cand["expression"]})
        else:
            rejected.append({"expression": cand["expression"], "kind": judged.get("kind"), "per_million": cand["per_million"]})
    deduped = drop_contained(kept)
    ranked = rank(deduped, args.final_max)
    rng = random.Random(7)
    pools = collect_clips(iter_segments(args.db), [it["key"] for it in ranked], rng)
    expressions: List[Dict[str, Any]] = []
    for item in ranked:
        clips = pick_clips(pools.get(item["key"], []), rng)
        if not clips:
            continue
        expressions.append(
            {
                "expression": item["expression"],
                "kind": item["kind"],
                "meaning_ko": item["meaning_ko"],
                "why_hard": item["why_hard"],
                "register": item["register"],
                "example": item["example"],
                "per_million": item["per_million"],
                "count": item["count"],
                "clips": clips,
            }
        )
    report = {
        "candidates": len(candidates),
        "judged": len(judged_pairs),
        "kept_before_dedupe": len(kept),
        "kept": len(expressions),
        "rejected": len(rejected),
        "kept_by_kind": counts_by_kind(expressions),
    }
    refuse_learning_dir(args.out)
    write_json(
        args.out,
        {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "counts": report, "expressions": expressions},
    )
    write_json(args.work_dir / "rejected.json", rejected)
    print(json.dumps(report, ensure_ascii=False))
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["candidates", "judge", "finalize", "all"])
    parser.add_argument("--db", type=Path, default=clipdb.db_path())
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=CANDIDATE_LIMIT)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--max-batches", type=int, default=0)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--fallback-model", default=FALLBACK_MODEL)
    parser.add_argument("--print-timeout", type=int, default=600)
    parser.add_argument("--final-max", type=int, default=FINAL_MAX)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    refuse_learning_dir(args.work_dir)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    stages = ["candidates", "judge", "finalize"] if args.stage == "all" else [args.stage]
    for stage in stages:
        code = {"candidates": cmd_candidates, "judge": cmd_judge, "finalize": cmd_finalize}[stage](args)
        if code != EXIT_OK:
            return code
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
