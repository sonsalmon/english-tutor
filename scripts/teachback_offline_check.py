# teach-back 서버 로직의 모델 없는(self-check) 점검.
#
# Vertex 모델을 부르지 않고 다음을 확인한다.
#   (a) 임시 학습 폴더에 차단어에 걸리는 절과 정상 절을 넣고 lesson_dump(작업실
#       코드 재사용)가 정상 절만 내는지 — 가짜 blocklist.txt 사용
#   (b) 차단어 목록이 없으면 오류가 나고 원문으로 대체하지 않는지
#   (c) date 정규식이 잘못된 형식을 거부하는지 (서버·dump 양쪽)
#   (d) teach-back 정규화가 계약 키를 만들고 cause를 4개 중 하나로 고정하는지,
#       teachback/에 저장하는지, 빈 결과는 재시도 뒤 예외가 되는지
#   (e) auth mode별 제한 시간(teachback 900 / 일반 180, 환경변수 반영)
#   (f) lesson_dump 하위 프로세스가 15초를 넘기면 504 + 한국어 메시지
#   (g) lesson_text가 프런트와 같은 형식(## heading\nbody, 빈 제목은 본문만)으로
#       이어 6000자에서 자르는지
#   (h) 준비 화면이 빈 절일 때 Start를 막고 안내 문구를 보여 주는지
#
# 실행: 저장소 루트에서
#   /Users/sonsalmom/dev/immergo/.venv/bin/python scripts/teachback_offline_check.py
#
# 작업실 코드 경로가 다르면 WORKROOM_CLI_DIR 환경변수로 지정한다.

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_WORKROOM_CLI_DIR = "~/dev/workroom/cli"
WORKROOM_CLI_DIR = os.path.expanduser(
    os.getenv("WORKROOM_CLI_DIR") or DEFAULT_WORKROOM_CLI_DIR
)
LESSON_DUMP = REPO_ROOT / "scripts" / "lesson_dump.py"
PYTHON = os.getenv("LESSON_PYTHON") or "python3"

from server import lesson  # noqa: E402
from server import tutor  # noqa: E402

TOPIC = "security-career"
RECORD_DATE = "2026-10-12"

# 차단어에 걸리지 않고 개인 주의어에도 안 걸리는 정상 절 본문.
_NORMAL_BODY = "Hashing turns a password into a fixed-length digest for comparison."
# 차단어 SECRETWORD가 들어간 절(blocklist.txt가 이 낱말을 막는다).
_BLOCKED_BODY = "The SECRETWORD value is mixed in before hashing."
_DAY_MD = "\n".join(
    [
        "# Day 1 Notes",
        "",
        "## Hashing basics",
        _NORMAL_BODY,
        "",
        "## Private detail",
        _BLOCKED_BODY,
        "",
    ]
)


def _write_day(root: Path, date: str = RECORD_DATE, text: str = _DAY_MD) -> Path:
    records_dir = root / TOPIC / "learning-records"
    records_dir.mkdir(parents=True, exist_ok=True)
    path = records_dir / f"{date}.md"
    path.write_text(text, encoding="utf-8")
    return path


def _dump_env(learning_root: Path, data_dir: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = WORKROOM_CLI_DIR + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    env["LEARNING_ROOT"] = str(learning_root)
    env["WORKROOM_DATA_DIR"] = str(data_dir)
    env["LEARNING_TOPIC"] = TOPIC
    env["WORKROOM_CLI_DIR"] = WORKROOM_CLI_DIR
    return env


def check_filter_and_hidden_count() -> None:
    """(a) 차단어에 걸리는 절은 빼고 정상 절만, 개수는 hidden_count로."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "learning"
        data_dir = Path(tmp) / "workroom"
        data_dir.mkdir()
        (data_dir / "blocklist.txt").write_text("SECRETWORD\n", encoding="utf-8")
        _write_day(root)

        # 1) 서버 계층(get_lesson)으로 확인.
        os.environ["LEARNING_ROOT"] = str(root)
        os.environ["WORKROOM_DATA_DIR"] = str(data_dir)
        os.environ["LEARNING_TOPIC"] = TOPIC
        os.environ["WORKROOM_CLI_DIR"] = WORKROOM_CLI_DIR
        try:
            data = lesson.get_lesson(RECORD_DATE)
        finally:
            for key in ("LEARNING_ROOT", "WORKROOM_DATA_DIR", "LEARNING_TOPIC", "WORKROOM_CLI_DIR"):
                os.environ.pop(key, None)

        assert data["date"] == RECORD_DATE, data
        assert data["topic"] == TOPIC, data
        assert data["dates"] == [RECORD_DATE], data
        assert data["day_title"] == "Day 1 Notes", data
        assert data["hidden_count"] == 1, data
        headings = [s["heading"] for s in data["sections"]]
        assert headings == ["Hashing basics"], headings
        assert data["sections"][0]["body"] == _NORMAL_BODY, data["sections"][0]
        assert "SECRETWORD" not in json.dumps(data, ensure_ascii=False), "차단어가 노출됨"

        # 2) dump 스크립트 단독으로도 같은 결과를 내는지(하위 프로세스 계약).
        completed = subprocess.run(
            [PYTHON, str(LESSON_DUMP), "--date", RECORD_DATE],
            capture_output=True,
            text=True,
            env=_dump_env(root, data_dir),
        )
        assert completed.returncode == 0, completed.stderr
        dumped = json.loads(completed.stdout)
        assert dumped == data, (dumped, data)


def check_missing_blocklist() -> None:
    """(b) 차단어 목록이 없으면 오류(원문 대체 없음)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "learning"
        data_dir = Path(tmp) / "workroom"
        data_dir.mkdir()  # blocklist.txt 없음
        _write_day(root)

        # dump는 blocklist 오류를 내고 0이 아닌 코드로 끝난다.
        completed = subprocess.run(
            [PYTHON, str(LESSON_DUMP), "--date", RECORD_DATE],
            capture_output=True,
            text=True,
            env=_dump_env(root, data_dir),
        )
        assert completed.returncode != 0, completed.stdout
        err = json.loads(completed.stdout)
        assert err.get("error") == "blocklist", err

        # 서버 계층은 LessonBlocklistError(500)를 올린다 — 원문을 돌려주지 않는다.
        os.environ["LEARNING_ROOT"] = str(root)
        os.environ["WORKROOM_DATA_DIR"] = str(data_dir)
        os.environ["LEARNING_TOPIC"] = TOPIC
        os.environ["WORKROOM_CLI_DIR"] = WORKROOM_CLI_DIR
        try:
            try:
                lesson.get_lesson(RECORD_DATE)
            except lesson.LessonBlocklistError as e:
                assert e.status_code == 500, e.status_code
            else:
                raise AssertionError("차단어 목록이 없으면 LessonBlocklistError여야 함")
        finally:
            for key in ("LEARNING_ROOT", "WORKROOM_DATA_DIR", "LEARNING_TOPIC", "WORKROOM_CLI_DIR"):
                os.environ.pop(key, None)


def check_date_regex() -> None:
    """(c) date 정규식 거부 사례(ASCII fullmatch)."""
    bad_dates = (
        "2026-1-01",
        "2026/10/12",
        "2026-10-12\n",
        "../2026-10-12",
        " 2026-10-12",
        "２０２６-10-12",
        "2026-1O-12",
        "",
    )
    for bad in bad_dates:
        try:
            lesson.validate_date(bad)
        except lesson.LessonDateError:
            pass
        else:
            raise AssertionError(f"거부되어야 함: {bad!r}")

    assert lesson.validate_date("2026-10-12") == "2026-10-12"
    assert lesson.validate_date(None) is None

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "learning"
        data_dir = Path(tmp) / "workroom"
        data_dir.mkdir()
        (data_dir / "blocklist.txt").write_text("SECRETWORD\n", encoding="utf-8")
        _write_day(root)

        completed = subprocess.run(
            [PYTHON, str(LESSON_DUMP), "--date", "2026-1-01"],
            capture_output=True,
            text=True,
            env=_dump_env(root, data_dir),
        )
        assert completed.returncode != 0, completed.stdout
        assert json.loads(completed.stdout).get("error") == "bad_date", completed.stdout


def check_teachback_normalization() -> None:
    """(d) teach-back 정규화: 계약 키·cause 고정·상한·빈 결과 재시도."""
    fake = {
        "unanswered": [
            {
                "question": "Maya: What is hashing?",
                "teacher_said": "Hashing is ...",
                "cause": "English",  # 대문자 -> english로 고정
                "evidence": "영어로 막혔어요.",
                "parked": True,
            },
            {
                "question": "Leo: Why salt?",
                "teacher_said": "",
                "cause": "banana",  # 알 수 없는 값 -> unclear로 고정
                "evidence": "노트와 설명이 달라요.",
            },
            {"question": "", "teacher_said": "", "cause": "english", "evidence": ""},  # 버림
            "not-a-dict",
        ],
        "corrections": [{"said": "I am agree", "better": "I agree", "why": "be동사 불필요"}],
        "good": [{"said": "Nice example.", "note": "구체적이었어요."}],
        "vocab": [{"word": "salt", "meaning_ko": "소금(무작위 값)", "example": "Add salt.", "etymology": ""}],
        "pragmatics": [{"pattern": "Check understanding", "note": "되물어 확인하기"}],
        "retry": {"goal": "Define terms first.", "target_phrases": ["Let me explain", ""]},
        "extra": "ignored",
    }

    out = tutor.normalize_teachback_json(json.dumps(fake))
    assert set(out) == {"corrections", "good", "vocab", "pragmatics", "retry", "unanswered"}, set(out)
    assert len(out["unanswered"]) == 2, out["unanswered"]
    for row in out["unanswered"]:
        assert row["cause"] in tutor.CAUSES, row
        assert isinstance(row["parked"], bool), row
        assert set(row) == {"question", "teacher_said", "cause", "evidence", "parked"}, row
    assert out["unanswered"][0]["cause"] == "english", out["unanswered"][0]
    assert out["unanswered"][1]["cause"] == "unclear", out["unanswered"][1]
    assert out["unanswered"][0]["parked"] is True
    assert out["unanswered"][1]["parked"] is False
    assert out["retry"]["target_phrases"] == ["Let me explain"], out["retry"]

    # 상한 8.
    many = {"unanswered": [
        {"question": f"Sam: q{i}", "teacher_said": "x", "cause": "english", "evidence": "e"}
        for i in range(10)
    ]}
    assert len(tutor.normalize_teachback_json(json.dumps(many))["unanswered"]) == tutor.MAX_UNANSWERED == 8

    # 빈 결과는 재시도(2회) 뒤 예외.
    empty = json.dumps({
        "unanswered": [],
        "corrections": [], "good": [], "vocab": [], "pragmatics": [],
        "retry": {"goal": "", "target_phrases": []},
    })
    assert tutor.is_empty_teachback_result(tutor.normalize_teachback_json(empty))
    calls = {"n": 0}

    def always_empty(_prompt):
        calls["n"] += 1
        return empty

    try:
        tutor.analyze_teachback("**Me:** hi", "notes", generate_text=always_empty)
    except tutor.TutoringAnalysisError:
        pass
    else:
        raise AssertionError("빈 teach-back 결과는 TutoringAnalysisError여야 함")
    assert calls["n"] == 2, calls

    # 첫 시도만 비고 두 번째에 내용이 있으면 성공한다.
    seq = {"n": 0}

    def empty_then_ok(_prompt):
        seq["n"] += 1
        return empty if seq["n"] == 1 else json.dumps(fake)

    result = tutor.analyze_teachback("**Me:** hi", "notes", generate_text=empty_then_ok)
    assert seq["n"] == 2 and result["unanswered"], result


def check_teachback_save() -> None:
    """(d) teachback/에 저장하고 lesson_date를 붙이며, 저장 실패는 saved=False."""
    fake = {
        "unanswered": [
            {"question": "Maya: Why?", "teacher_said": "", "cause": "understanding", "evidence": "모호함"}
        ],
        "corrections": [], "good": [], "vocab": [], "pragmatics": [],
        "retry": {"goal": "Clarify.", "target_phrases": ["In other words"]},
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sessions = root / "sessions"
        sessions.mkdir()
        transcript = sessions / "2026-10-12-120000.md"
        transcript.write_text("**Me:** hi\n", encoding="utf-8")

        os.environ["TEACHBACK_DIR"] = str(root / "teachback")
        try:
            data, saved = tutor.run_teachback(
                transcript, "hidden notes", "2026-10-12",
                generate_text=lambda _p: json.dumps(fake),
            )
            assert saved is True, saved
            assert data["lesson_date"] == "2026-10-12", data
            saved_file = root / "teachback" / "2026-10-12-120000.json"
            assert saved_file.is_file(), saved_file
            assert json.loads(saved_file.read_text(encoding="utf-8")) == data

            # 저장 위치가 tutoring/이 아님.
            assert not (root / "tutoring" / "2026-10-12-120000.json").exists()
        finally:
            os.environ.pop("TEACHBACK_DIR", None)

        # 저장 실패(디렉터리 자리를 파일이 차지) -> 예외 없이 saved=False.
        blocker = root / "blocker"
        blocker.write_text("x", encoding="utf-8")
        os.environ["TEACHBACK_DIR"] = str(blocker)
        try:
            _data, saved = tutor.run_teachback(
                transcript, "hidden notes", "2026-10-12",
                generate_text=lambda _p: json.dumps(fake),
            )
            assert saved is False, saved
        finally:
            os.environ.pop("TEACHBACK_DIR", None)


def check_auth_time_limits() -> None:
    """(e) auth mode별 제한 시간."""
    assert lesson.resolve_session_time_limit("teachback", 180, 900) == 900
    assert lesson.resolve_session_time_limit(None, 180, 900) == 180
    assert lesson.resolve_session_time_limit("roleplay", 180, 900) == 180
    # teachback 제한 인자를 안 주면 기본 900.
    assert lesson.resolve_session_time_limit("teachback", 180) == lesson.DEFAULT_TEACHBACK_TIME_LIMIT == 900
    assert lesson.DEFAULT_SESSION_TIME_LIMIT == 180

    # 환경변수: 기본값과 재정의.
    assert lesson.session_time_limit_from_env("teachback", env={}) == 900
    assert lesson.session_time_limit_from_env(None, env={}) == 180
    assert lesson.session_time_limit_from_env("teachback", env={"TEACHBACK_TIME_LIMIT": "600"}) == 600
    assert lesson.session_time_limit_from_env(None, env={"SESSION_TIME_LIMIT": "240"}) == 240
    assert lesson.session_time_limit_from_env("teachback", env={"SESSION_TIME_LIMIT": "240"}) == 900


def check_lesson_subprocess_timeout() -> None:
    """(f) lesson_dump 하위 프로세스가 15초를 넘기면 504 + 한국어 메시지."""
    assert lesson.LESSON_SUBPROCESS_TIMEOUT_SEC == 15, lesson.LESSON_SUBPROCESS_TIMEOUT_SEC

    original_run = lesson.subprocess.run
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        raise lesson.subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    lesson.subprocess.run = fake_run
    try:
        try:
            lesson.get_lesson(RECORD_DATE)
        except lesson.LessonTimeoutError as e:
            assert e.status_code == 504, e.status_code
            assert str(e) == "수업 기록을 읽는 데 너무 오래 걸려요.", str(e)
        else:
            raise AssertionError("시간 초과는 LessonTimeoutError여야 함")
    finally:
        lesson.subprocess.run = original_run

    # subprocess.run에 시간 제한이 실제로 걸려 있어야 한다.
    assert captured.get("timeout") == lesson.LESSON_SUBPROCESS_TIMEOUT_SEC, captured


def check_lesson_text_format() -> None:
    """(g) lesson_text가 프런트 _lessonText와 같은 형식으로 이어 6000자에서 자른다."""
    data = {
        "sections": [
            {"heading": "Hashing basics", "body": "Hashing turns a password into a digest."},
            {"heading": "   ", "body": "제목이 빈 절은 본문만 남는다"},
            {"heading": "Empty body", "body": "  "},
            {"heading": "", "body": "   "},
        ]
    }
    expected = "\n\n".join(
        [
            "## Hashing basics\nHashing turns a password into a digest.",
            "제목이 빈 절은 본문만 남는다",
            "## Empty body",
        ]
    )
    assert lesson.lesson_text(data) == expected, lesson.lesson_text(data)

    # 6000자에서 자른다.
    big = {"sections": [{"heading": "H", "body": "x" * 7000}]}
    assert lesson.MAX_LESSON_TEXT == 6000
    assert len(lesson.lesson_text(big)) == 6000

    # 형식이 어긋난 입력은 빈 문자열.
    assert lesson.lesson_text(None) == ""
    assert lesson.lesson_text({"sections": "nope"}) == ""


def check_prep_empty_sections_guard() -> None:
    """(h) 가르칠 절이 0개면 준비 화면이 Start를 막고 안내 문구를 보여 준다."""
    src = (REPO_ROOT / "src" / "screens" / "TeachbackPrep.tsx").read_text(encoding="utf-8")
    assert "이 날짜는 보낼 수 있는 내용이 없어요(거름망에 모두 걸림)" in src, "빈 절 안내 문구가 없음"
    assert "const canStart = !!lesson && lesson.sections.length > 0;" in src, "빈 절일 때 Start를 막는 코드가 없음"
    assert "disabled={!canStart}" in src, "Start 버튼이 canStart를 쓰지 않음"


def main() -> int:
    if not Path(WORKROOM_CLI_DIR).is_dir():
        print(f"SKIP: 작업실 코드 폴더를 찾지 못했습니다: {WORKROOM_CLI_DIR}")
        print("      WORKROOM_CLI_DIR 환경변수로 지정하세요.")
        return 1

    check_filter_and_hidden_count()
    check_missing_blocklist()
    check_date_regex()
    check_teachback_normalization()
    check_teachback_save()
    check_auth_time_limits()
    check_lesson_subprocess_timeout()
    check_lesson_text_format()
    check_prep_empty_sections_guard()
    print("teachback offline check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
