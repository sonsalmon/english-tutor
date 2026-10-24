#!/usr/bin/env python3
"""원어민 표현 목록에 say_ko(말하고 싶은 한국어 한 문장)를 붙인다.

say_ko: 한국인 학습자가 실제로 입 밖에 내고 싶은 짧은 구어 한국어 한 문장. 원어민이 그 말을 영어로 할 때 이 표현을 쓴다.
  예) "I'm screwed" -> "나 완전 망했어!", "come up with" -> "좋은 생각이 났어", "you know" -> "있잖아, 그거 있잖아".
읽는 목록(--src)은 build_native_expressions.py의 결과 JSON이다. 40개씩 agy(Gemini)로 보내고(배치마다 --work-dir에 저장해 이어 돌릴 수 있다),
say_ko를 붙인 사본을 --out에 쓴다. 원본과 학습 폴더(~/dev/learning/english)에는 쓰지 않는다. 설치는 사람이 백업 후 직접 한다.
agy 호출·재시도·JSON 읽기는 build_native_expressions.py의 것을 그대로 가져다 쓴다.
"""

import argparse
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import build_native_expressions as bne  # noqa: E402

DEFAULT_SRC = Path.home() / "dev" / "learning" / "english" / "clipdb" / "native_expressions.json"
DEFAULT_OUT = Path.home() / "dev" / ".omo" / "dag" / "clip-say" / "native-expressions-say.json"
DEFAULT_WORK_DIR = Path.home() / "dev" / ".omo" / "dag" / "clip-say" / "work"
SAY_MAX_CHARS = 40
BATCH_SIZE = bne.BATCH_SIZE

PROMPT_HEAD = """You are helping Korean learners of English. For each English expression below, write ONE short, natural, spoken Korean sentence
(say_ko) that a Korean learner would actually want to say in a real situation, such that a native English speaker would use exactly
this expression to say it.

Rules:
- say_ko is casual spoken Korean (해요체 or 반말 as friends would say), one sentence, at most 25 characters, no quotes.
- It must be the thing the learner WANTS TO SAY (the intention), not a dictionary definition and not a translation of the English words.
  Good: "I'm screwed" -> "나 완전 망했어!"; "come up with" -> "좋은 생각이 났어"; "you know" -> "있잖아, 그거 있잖아".
  Bad: "'끝내다'라는 뜻" (definition), "나는 나사로 박혔다" (literal).
- Do not write the English expression itself inside say_ko.
- Use the meaning and the example only to understand the sense.

Return JSON only: an array with one object per item, in the form {"id": <number>, "say_ko": "<Korean sentence>"}. No other text.

Items:
"""

_HANGUL = re.compile(r"[\uac00-\ud7a3]")


def clean_say(value: Any) -> Optional[str]:
    """say_ko 후보를 정리한다. 한글이 없거나 비었거나 너무 길면 None."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip("\"'“”‘’ ")
    if not text or len(text) > SAY_MAX_CHARS or not _HANGUL.search(text):
        return None
    return text


def prompt_for(batch: Sequence[Dict[str, Any]]) -> str:
    lines = []
    for i, entry in enumerate(batch, 1):
        lines.append(
            f'{i}. "{entry["expression"]}" ({entry.get("kind", "")}) meaning: {entry.get("meaning_ko", "")}'
            + (f' | example: "{entry["example"]}"' if entry.get("example") else "")
        )
    return PROMPT_HEAD + "\n".join(lines) + "\n"


def parse_say(output: str) -> Dict[int, str]:
    """모델 출력에서 {번호: say_ko}를 뽑는다(코드 울타리·앞뒤 설명·끝 쉼표가 있어도 읽을 수 있는 항목은 살린다)."""
    text = re.sub(r"```(?:json)?", "", output or "")
    items: List[Any] = []
    first, last = text.find("["), text.rfind("]")
    if 0 <= first < last:
        try:
            data = bne._load_json(text[first : last + 1])
            if isinstance(data, list):
                items = data
        except ValueError:
            items = []
    if not items:
        for fragment in bne._objects(text):
            try:
                items.append(bne._load_json(fragment))
            except ValueError:
                continue
    got: Dict[int, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        say = clean_say(item.get("say_ko"))
        if say:
            got.setdefault(item_id, say)
    return got


def say_batch(asker: "bne.Judge", batch: Sequence[Dict[str, Any]]) -> Dict[int, str]:
    """배치 안 번호(1부터) -> say_ko. 빠졌거나 쓸 수 없는 항목은 한 번 더 묻는다."""
    got: Dict[int, str] = {}
    todo = list(range(1, len(batch) + 1))
    for _ in range(3):
        if not todo:
            break
        sub = [batch[i - 1] for i in todo]
        parsed = parse_say(asker.ask(prompt_for(sub)))
        for local, say in parsed.items():
            if 1 <= local <= len(sub):
                got[todo[local - 1]] = say
        todo = [i for i in range(1, len(batch) + 1) if i not in got]
    return got


def load_source(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = {"expressions": data}
    if not isinstance(data, dict) or not isinstance(data.get("expressions"), list):
        raise SystemExit(f"표현 목록 형식이 아니에요: {path}")
    return data


def run(args: argparse.Namespace) -> int:
    bne.refuse_learning_dir(args.out.parent)
    bne.refuse_learning_dir(args.work_dir)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    data = load_source(args.src)
    entries: List[Dict[str, Any]] = data["expressions"]
    size = args.batch_size
    batches = [entries[i : i + size] for i in range(0, len(entries), size)]
    asker = bne.Judge(args.work_dir, args.model, args.fallback_model, args.print_timeout)
    results: Dict[int, Dict[int, str]] = {}
    lock = threading.Lock()

    def work(index: int) -> None:
        cache = args.work_dir / f"say-batch-{index:03d}.json"
        if cache.is_file() and not args.force:
            try:
                saved = {int(k): v for k, v in json.loads(cache.read_text(encoding="utf-8")).items()}
                if len(saved) == len(batches[index]):
                    with lock:
                        results[index] = saved
                    print(f"WORKING: clip-say - 배치 {index + 1}/{len(batches)} 건너뜀(저장분)", flush=True)
                    return
            except (OSError, ValueError):
                pass
        got = say_batch(asker, batches[index])
        bne.write_json(cache, {str(k): v for k, v in got.items()})
        with lock:
            results[index] = got
        print(f"WORKING: clip-say - 배치 {index + 1}/{len(batches)} {len(got)}/{len(batches[index])}개", flush=True)

    order = list(range(len(batches)))
    if args.max_batches:
        order = order[: args.max_batches]
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(work, order))
    except bne.StopPipeline as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return bne.EXIT_QUOTA

    done = 0
    for index, batch in enumerate(batches):
        got = results.get(index, {})
        for local, entry in enumerate(batch, 1):
            if local in got:
                entry["say_ko"] = got[local]
                done += 1
            else:
                entry.pop("say_ko", None)
    counts = data.get("counts")
    if isinstance(counts, dict):
        counts["say_ko"] = done
    else:
        data["say_ko_count"] = done
    bne.write_json(args.out, data)
    print(f"say_ko {done}/{len(entries)} -> {args.out} (모델 사용 {dict(asker.used)})")
    return bne.EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--max-batches", type=int, default=0)
    parser.add_argument("--model", default=bne.MODEL)
    parser.add_argument("--fallback-model", default=bne.FALLBACK_MODEL)
    parser.add_argument("--print-timeout", type=int, default=600)
    parser.add_argument("--force", action="store_true")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
