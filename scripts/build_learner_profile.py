# 첫 학습자 카드를 만든다(명세 5절 "첫 카드").
#
# 재료: tutoring/*.json, level-test/results/2026-10-07-rating.md, learning-records/*.md
# 기본은 dry-run(카드 JSON을 출력만 한다). 쓰려면 --write. 기존 카드는 history로 백업된다.
#
# 실행: 저장소 루트에서
#   .venv/bin/python scripts/build_learner_profile.py            # 출력만
#   .venv/bin/python scripts/build_learner_profile.py --write    # LEARNER_PROFILE_PATH에 쓰기

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from server.learner_profile import (  # noqa: E402
    ProfileError,
    build_initial_card,
    get_profile_path,
    write_profile,
)
from server.tutor import make_generate_text  # noqa: E402

DEFAULT_ROOT = "~/dev/learning/english"
RATING_FILE = "level-test/results/2026-10-07-rating.md"
MAX_FILE_CHARS = 30000


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")[:MAX_FILE_CHARS]


def gather_material(root: Path) -> str:
    parts = []
    for path in sorted((root / "tutoring").glob("*.json")):
        parts.append(f"## tutoring/{path.name}\n{_read(path)}")
    rating = root / RATING_FILE
    if rating.is_file():
        parts.append(f"## {RATING_FILE} (level test result: the source of `level`)\n{_read(rating)}")
    for path in sorted((root / "learning-records").glob("*.md")):
        parts.append(f"## learning-records/{path.name}\n{_read(path)}")
    return "\n\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="첫 학습자 카드를 만든다(기본 dry-run).")
    parser.add_argument("--root", default=DEFAULT_ROOT, help="학습 자료 폴더 (기본 %(default)s)")
    parser.add_argument("--write", action="store_true", help="카드 파일에 쓴다(기본은 출력만)")
    args = parser.parse_args()

    root = Path(os.path.expanduser(args.root))
    material = gather_material(root)
    if not material:
        print(f"재료가 없습니다: {root}", file=sys.stderr)
        return 1

    try:
        card = build_initial_card(material, generate_text=make_generate_text())
    except ProfileError as e:
        print(f"모델 출력이 카드 형식이 아닙니다: {e}", file=sys.stderr)
        return 1

    print(json.dumps(card, ensure_ascii=False, indent=2))
    if args.write:
        print(f"쓰기: {write_profile(card)}", file=sys.stderr)
    else:
        print(f"(dry-run: --write를 주면 {get_profile_path()}에 씁니다)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
