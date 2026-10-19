# 첫 학습자 카드를 기존 튜터링·레벨테스트 결과·학습 기록으로 만든다(docs/spec.md 5절 "첫 카드").
# 기본은 미리보기(카드 JSON 출력)만 한다. 카드 파일에 쓰려면 --write.
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / '.env')

from server.learner_profile import build_initial_card, get_profile_path, write_profile
from server.transcript_store import get_tutoring_dir
from server.tutor import make_generate_text

ENGLISH_DIR = Path(os.path.expanduser('~/dev/learning/english'))
LEVEL_TEST_RESULT = ENGLISH_DIR / 'level-test' / 'results' / '2026-10-07-rating.md'


def gather_material() -> str:
    parts = []
    for path in sorted(get_tutoring_dir().glob('*.json')):
        parts.append(f'## Call tutoring {path.name}\n{path.read_text(encoding="utf-8")}')
    parts.append(f'## Level test result {LEVEL_TEST_RESULT.name}\n{LEVEL_TEST_RESULT.read_text(encoding="utf-8")}')
    for path in sorted((ENGLISH_DIR / 'learning-records').glob('*.md')):
        parts.append(f'## Learning record {path.name}\n{path.read_text(encoding="utf-8")}')
    return '\n\n'.join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description='첫 학습자 카드 만들기')
    parser.add_argument('--write', action='store_true', help='카드 파일에 쓴다(기존 카드는 history에 복사)')
    args = parser.parse_args()

    card = build_initial_card(gather_material(), generate_text=make_generate_text())
    print(json.dumps(card, ensure_ascii=False, indent=2))
    if args.write:
        print(f'저장: {write_profile(card)}')
    else:
        print(f'미리보기만 했습니다. 쓰려면 --write (대상: {get_profile_path()})')


if __name__ == '__main__':
    main()
