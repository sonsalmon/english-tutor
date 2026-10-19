# 튜터링 분석 스모크 시험.
#
# 실제 통화 전문 파일(기본: 2026-10-12-093238.md)을 tutor.py의 함수에 넣어
# /api/tutor 로직이 계약 JSON을 만들고 파일로 저장하는지 확인한다.
# 모델 호출은 딱 한 번만 한다.
#
# 실행: 저장소 루트에서
#   .venv/bin/python scripts/tutor_smoke.py
#   (또는) python scripts/tutor_smoke.py
# ADC(구글 클라우드 로그인)와 .env의 PROJECT_ID·LOCATION이 필요하다.
# 다른 파일을 쓰려면: python scripts/tutor_smoke.py 2026-10-12-093238.md

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from server.tutor import (  # noqa: E402
    FILENAME_RE,
    MAX_CORRECTIONS,
    MAX_GOOD,
    MAX_VOCAB,
    get_tutoring_dir,
    resolve_transcript,
    tutor_transcript,
)

DEFAULT_FILENAME = "2026-10-12-093238.md"


def main() -> int:
    filename = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FILENAME
    if not FILENAME_RE.match(filename):
        print(f"FAIL: 파일명이 sessions/ 허용 패턴이 아님: {filename}")
        return 1

    # 1) 경로 해석(경로 주입 방지)만 먼저 점검한다. 모델 호출 없음.
    path = resolve_transcript(filename)
    print(f"입력 파일: {path}")
    assert path.is_file(), path

    # 2) 실제 분석 1회 + 저장.
    data = tutor_transcript(path)

    # 3) 고정 계약 검사.
    assert isinstance(data, dict), type(data)
    assert set(data) == {"corrections", "good", "vocab", "pragmatics", "retry"}, set(data)
    assert isinstance(data["corrections"], list) and len(data["corrections"]) <= MAX_CORRECTIONS
    assert isinstance(data["good"], list) and len(data["good"]) <= MAX_GOOD
    assert isinstance(data["vocab"], list) and len(data["vocab"]) <= MAX_VOCAB
    assert isinstance(data["pragmatics"], list)
    for row in data["corrections"]:
        assert set(row) == {"said", "better", "why"} and row["better"], row
    for row in data["good"]:
        assert set(row) == {"said", "note"}, row
    for row in data["vocab"]:
        assert set(row) == {"word", "meaning_ko", "example", "etymology"}, row
    for row in data["pragmatics"]:
        assert set(row) == {"pattern", "note"}, row
    assert set(data["retry"]) == {"goal", "target_phrases"}, data["retry"]
    assert isinstance(data["retry"]["target_phrases"], list)

    # 4) 저장 파일이 같은 파일명의 .json으로 남았는지 확인.
    saved = get_tutoring_dir() / (path.stem + ".json")
    assert saved.is_file(), saved
    on_disk = json.loads(saved.read_text(encoding="utf-8"))
    assert on_disk == data, "저장 내용과 응답이 다름"
    print(f"저장 파일: {saved}")
    print(
        "요약: 교정 {c} · 좋은 문장 {g} · 단어 {v} · 화용 {p} · 목표 문구 {t}".format(
            c=len(data["corrections"]),
            g=len(data["good"]),
            v=len(data["vocab"]),
            p=len(data["pragmatics"]),
            t=len(data["retry"]["target_phrases"]),
        )
    )
    print("tutor smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
