# 튜터링 분석의 모델 없는(self-check) 점검.
#
# Vertex 모델을 부르지 않고 다음을 확인한다.
#   (a) mtime 필터가 "어제" 전사 파일을 걸러내는지 (임시 폴더)
#   (b) 5개 섹션이 모두 빈 JSON은 재시도(2회) 뒤 예외가 되는지
#   (c) 파일명 정규식이 줄바꿈·비ASCII 숫자·경로 주입을 거부하는지
#   (d) 저장 실패 여부가 saved로 구분되고 실패 시 기존 JSON을 덮어쓰지 않는지
#
# 실행: 저장소 루트에서
#   /Users/sonsalmom/dev/immergo/.venv/bin/python scripts/tutor_offline_check.py

import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from server.tutor import (  # noqa: E402
    FILENAME_RE,
    TutoringAnalysisError,
    analyze_transcript,
    is_empty_result,
    latest_transcript_since,
    normalize_tutor_json,
    run_tutoring,
)

_EMPTY_JSON = (
    '{"corrections": [], "good": [], "vocab": [], "pragmatics": [], '
    '"retry": {"goal": "", "target_phrases": []}}'
)
_FAKE_JSON = json.dumps(
    {
        "corrections": [{"said": "I am agree", "better": "I agree", "why": "be동사 불필요"}],
        "good": [{"said": "I'll circle back.", "note": "자연스러움"}],
        "vocab": [{"word": "circle back", "meaning_ko": "재논의", "example": "Let's circle back.", "etymology": ""}],
        "pragmatics": [{"pattern": "Bottom line first", "note": "결론 먼저"}],
        "retry": {"goal": "Lead with your bottom line.", "target_phrases": ["Here's the bottom line"]},
    }
)


def check_mtime_filter() -> None:
    """(a) started_at 이후 파일만 후보로 삼고, 어제 파일로 되돌아가지 않는다."""
    now = time.time()
    yesterday = now - 86400.0
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        old = d / "2026-10-11-120000.md"
        new = d / "2026-10-12-120000.md"
        old.write_text("**Me:** old\n", encoding="utf-8")
        new.write_text("**Me:** new\n", encoding="utf-8")
        os.utime(old, (yesterday, yesterday))
        os.utime(new, (now, now))

        picked = latest_transcript_since(int(now * 1000), directory=d)
        assert picked == new, f"오늘 파일을 골라야 함: {picked}"

        assert latest_transcript_since(None, directory=d) == new

        # 오늘 파일이 없으면 어제 파일로 폴백하지 않고 None.
        new.unlink()
        assert latest_transcript_since(int(now * 1000), directory=d) is None

        # 형식에 맞지 않는 파일은 후보에서 빠진다.
        (d / "notes.md").write_text("x", encoding="utf-8")
        os.utime(d / "notes.md", (now, now))
        assert latest_transcript_since(int(now * 1000), directory=d) is None


def check_empty_result() -> None:
    """(b) 빈 JSON은 재시도 뒤 예외, 내용이 있으면 성공."""
    calls = {"n": 0}

    def always_empty(_prompt):
        calls["n"] += 1
        return _EMPTY_JSON

    try:
        analyze_transcript("**Me:** hi", generate_text=always_empty)
    except TutoringAnalysisError:
        pass
    else:
        raise AssertionError("빈 결과는 TutoringAnalysisError여야 함")
    assert calls["n"] == 2, f"2회 시도해야 함: {calls}"

    assert is_empty_result(normalize_tutor_json(_EMPTY_JSON))

    # 첫 시도만 비고 두 번째에 내용이 있으면 성공한다.
    seq = {"n": 0}

    def empty_then_ok(_prompt):
        seq["n"] += 1
        return _EMPTY_JSON if seq["n"] == 1 else _FAKE_JSON

    out = analyze_transcript("**Me:** hi", generate_text=empty_then_ok)
    assert seq["n"] == 2 and out["good"], out


def check_filename_re() -> None:
    """(c) 줄바꿈·비ASCII 숫자·경로 주입을 거부한다."""
    assert FILENAME_RE.fullmatch("2026-10-12-093238.md")
    for bad in (
        "2026-10-12-093238.md\n",
        "../x.md",
        "/etc/passwd",
        "a/b.md",
        "notes.txt",
        "2026-10-12-09323.md",
        "2026-1O-12-093238.md",
        "２０２６-10-12-093238.md",
    ):
        assert FILENAME_RE.fullmatch(bad) is None, f"거부되어야 함: {bad!r}"


def check_save_status() -> None:
    """(d) 저장 성공은 saved=True, 실패 시 기존 JSON을 덮어쓰지 않는다."""
    now = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sessions = root / "sessions"
        tutoring = root / "tutoring"
        sessions.mkdir()
        transcript = sessions / "2026-10-12-120000.md"
        transcript.write_text("**Me:** hi\n", encoding="utf-8")
        os.utime(transcript, (now, now))

        os.environ["TUTORING_DIR"] = str(tutoring)
        try:
            data, saved = run_tutoring(transcript, generate_text=lambda _p: _FAKE_JSON)
            assert saved is True, saved
            saved_file = tutoring / "2026-10-12-120000.json"
            assert saved_file.is_file(), saved_file
            assert json.loads(saved_file.read_text(encoding="utf-8")) == data

            # 분석이 실패하면 예외가 나고 저장 파일은 그대로다.
            before = saved_file.read_text(encoding="utf-8")
            try:
                run_tutoring(transcript, generate_text=lambda _p: _EMPTY_JSON)
            except TutoringAnalysisError:
                pass
            else:
                raise AssertionError("빈 결과는 예외여야 함")
            assert saved_file.read_text(encoding="utf-8") == before, "빈 결과로 덮어쓰면 안 됨"
        finally:
            os.environ.pop("TUTORING_DIR", None)


def check_us_style_filter() -> None:
    """(e) us_style는 지어낸 said와 학습자가 이미 말한 natural을 버리고, pragmatics는 빈 목록이다."""
    transcript = "**Me:** How old are you?\n**Me:** Sorry?\n"
    raw = {
        "corrections": [{"said": "a", "better": "b c", "why": "d"}],
        "pragmatics": [{"pattern": "Bottom line first", "note": "결론 먼저"}],
        "us_style": [
            {"said": "How old are you?", "korean_way": "k", "natural": "So, what do you do?", "why": "w"},
            {"said": "How old are you?", "korean_way": "k", "natural": "Sorry?", "why": "w"},
            {"said": "never said this at all", "korean_way": "k", "natural": "Thanks for jumping on this", "why": "w"},
        ],
    }
    out = normalize_tutor_json(raw, transcript)
    assert [r["natural"] for r in out["us_style"]] == ["So, what do you do?"], out["us_style"]
    assert out["pragmatics"] == [], out["pragmatics"]
    assert not is_empty_result({**normalize_tutor_json({}), "us_style": out["us_style"]})


def main() -> int:
    check_mtime_filter()
    check_empty_result()
    check_filename_re()
    check_save_status()
    check_us_style_filter()
    print("tutor offline check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
