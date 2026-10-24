#!/usr/bin/env python3
"""v1 기억의 12개 상한 때문에 밀려난 사실을 history/ 백업에서 되살린다(한 번 쓰는 정리 도구).

친구마다 history/<친구>-*.json 백업을 모두 읽어, 지금 기억에 없는 사실만 중요도 2·출처 history로 더한다.
기본은 미리 보기이고, --apply 를 줄 때만 쓴다(쓰기 전에 지금 파일을 history/에 한 번 더 백업한다).
  .venv/bin/python scripts/recover_memory_history.py            # 미리 보기
  .venv/bin/python scripts/recover_memory_history.py --apply    # 반영
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import partner_memory as pm  # noqa: E402

RECOVERED_IMPORTANCE = 2


def fact_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def recover(partner_id: str, apply: bool, now: datetime) -> list:
    current = pm.load_memory(partner_id)
    if current is None:
        return []
    have = {fact_key(f["text"]) for f in current["facts"]}
    found = []
    for path in sorted((pm.get_memory_dir() / pm.HISTORY_DIR_NAME).glob(f"{partner_id}-*.json")):
        try:
            old = pm.normalize(json.loads(path.read_text(encoding="utf-8")), partner_id, now)
        except (OSError, ValueError):
            continue
        for fact in old["facts"]:
            key = fact_key(fact["text"])
            if key and key not in have:
                have.add(key)
                found.append(fact)
    if apply and found:
        facts = list(current["facts"])
        for fact in found:
            facts.append({
                **fact,
                "id": pm._next_fact_id(facts),
                "importance": RECOVERED_IMPORTANCE,
                "status": "valid",
                "until": None,
                "source": "history",
            })
        pm.write_memory(partner_id, {**current, "facts": pm.sort_facts(facts)}, now)
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="history 백업에서 밀려난 친구 기억 사실 되살리기")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    now = datetime.now(pm.KST)
    for partner_id in pm.PARTNER_IDS:
        found = recover(partner_id, args.apply, now)
        if found:
            print(f"{partner_id}: {len(found)}개 {'되살림' if args.apply else '되살릴 수 있음'}")
            for fact in found:
                print(f"  - ({fact.get('last_seen')}) {fact['text']}")


if __name__ == "__main__":
    main()
