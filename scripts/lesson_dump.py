# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""학습 기록(learning-records/*.md)을 작업실 거르기 코드로 걸러 JSON을 stdout에 낸다.

서버(server/lesson.py)가 하위 프로세스로 실행한다. 작업실 저장소 파일은 읽기만
하고 고치지 않는다. 표준 라이브러리 + workroom_cli만 쓴다.

환경변수:
- LEARNING_ROOT   학습 폴더 루트(기본 ~/dev/learning)
- LEARNING_TOPIC  소재 폴더 이름(기본 security-career)
- WORKROOM_DATA_DIR  차단어 파일 위치(기본 ~/.workroom)
- WORKROOM_CLI_DIR   workroom_cli 패키지 상위 폴더(기본 ~/dev/workroom/cli)

성공하면 계약 1 JSON을 stdout에 쓴다. 실패하면 {"error": <kind>, "message": ...}
를 stdout에 쓰고 0이 아닌 코드로 끝낸다(kind: no_records|blocklist|bad_date).
거르지 않은 원문으로 대체하지 않는다.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$", re.ASCII)
RECENT_DATES = 7

DEFAULT_LEARNING_ROOT = "~/dev/learning"
DEFAULT_TOPIC = "security-career"
DEFAULT_WORKROOM_DATA_DIR = "~/.workroom"
DEFAULT_WORKROOM_CLI_DIR = "~/dev/workroom/cli"


def _add_cli_dir_to_path() -> str:
    cli_dir = os.path.expanduser(os.getenv("WORKROOM_CLI_DIR") or DEFAULT_WORKROOM_CLI_DIR)
    if cli_dir and cli_dir not in sys.path:
        sys.path.insert(0, cli_dir)
    return cli_dir


_cli_dir = _add_cli_dir_to_path()

from workroom_cli import records  # noqa: E402
from workroom_cli.filters import BlocklistError, load_blocklist  # noqa: E402


def _fail(kind: str, message: str) -> "None":
    json.dump({"error": kind, "message": message}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.stdout.flush()
    sys.exit(1)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="걸러낸 수업 자료를 JSON으로 낸다.")
    parser.add_argument("--date", default=None, help="수업 날짜 YYYY-MM-DD(생략 시 가장 최근)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)

    if args.date is not None and DATE_RE.fullmatch(args.date) is None:
        _fail("bad_date", "날짜 형식이 올바르지 않습니다(YYYY-MM-DD).")

    learning_root = Path(os.path.expanduser(os.getenv("LEARNING_ROOT") or DEFAULT_LEARNING_ROOT))
    data_dir = Path(os.path.expanduser(os.getenv("WORKROOM_DATA_DIR") or DEFAULT_WORKROOM_DATA_DIR))
    topic = os.getenv("LEARNING_TOPIC") or DEFAULT_TOPIC

    records_dir = learning_root / topic / "learning-records"
    files = records.list_day_files(records_dir)  # (date, path) 날짜 오름차순
    if not files:
        _fail("no_records", "그날의 학습 기록이 없어요.")

    date_to_path = {rec_date: path for rec_date, path in files}
    dates_desc = [rec_date for rec_date, _ in reversed(files)][:RECENT_DATES]

    chosen = args.date or dates_desc[0]
    path = date_to_path.get(chosen)
    if path is None:
        _fail("no_records", f"{chosen} 날짜의 학습 기록이 없어요.")

    # 차단어 목록이 없거나 깨지면 여기서 BlocklistError가 난다(원문 대체 없음).
    try:
        blocked = load_blocklist(data_dir)
    except BlocklistError as e:
        _fail("blocklist", str(e))

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        _fail("no_records", f"학습 기록을 읽지 못했어요: {e}")

    result = records.day_rows(topic, chosen, text, blocked)

    sections = [
        {"heading": row["heading"], "body": row["body"]}
        for row in result.rows
        if not row["filtered"]
    ]
    hidden_count = sum(1 for row in result.rows if row["filtered"])

    day_title = ""
    for row in result.rows:
        if row["day_title"]:
            day_title = row["day_title"]
            break

    payload = {
        "topic": topic,
        "date": chosen,
        "dates": dates_desc,
        "day_title": day_title,
        "sections": sections,
        "hidden_count": hidden_count,
    }
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
