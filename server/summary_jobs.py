"""통화 정리(튜터링) 작업 등록부.

통화가 끝나면 서버가 스스로 정리 작업을 걸고, 화면이 부르는 `/api/tutor`는 같은 작업에 합류한다.
통화당(전문 stem당) 작업은 하나다: 돌고 있거나 끝난 작업이 있으면 새로 만들지 않아 모델을 두 번 부르지 않는다.
작업은 HTTP 요청과 묶이지 않은 asyncio 작업이라 화면을 닫아도 끝까지 돈다.

작업에 필요한 입력(mode·수업 날짜·연습 단어)은 통화를 걸 때 서버가 받아 두었다가 통화가 저장될 때
`tutoring/<stem>.job.json`으로 남긴다. 서버가 재시작된 뒤에도 같은 입력으로 다시 정리할 수 있다.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from server.transcript_store import get_tutoring_dir

logger = logging.getLogger(__name__)

PENDING = "pending"  # 전문은 있지만 요약도 돌고 있는 작업도 없다(재시작 직후·옛 통화·실패한 저장)
RUNNING = "running"
DONE = "done"
FAILED = "failed"
STATUSES = (PENDING, RUNNING, DONE, FAILED)

MAX_PRACTICE_WORDS = 10
# 끝난 작업(결과·실패)을 메모리에 남기는 개수. 도는 작업은 세지 않는다.
KEEP_FINISHED = 30
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)


@dataclass(frozen=True)
class JobSpec:
    """정리에 필요한 입력. 화면이 예전에 /api/tutor 본문으로 보내던 값이다."""

    mode: str = "mission"
    lesson_date: Optional[str] = None
    practice_words: Tuple[str, ...] = ()

    def to_json(self) -> Dict[str, Any]:
        return {"mode": self.mode, "lesson_date": self.lesson_date, "practice_words": list(self.practice_words)}

    @classmethod
    def from_json(cls, data: Any) -> "JobSpec":
        if not isinstance(data, dict):
            raise ValueError("작업 입력 형식이 틀립니다")
        mode = data.get("mode")
        date = data.get("lesson_date")
        words = data.get("practice_words")
        return cls(
            mode=mode if isinstance(mode, str) and mode else "mission",
            lesson_date=date if isinstance(date, str) and _DATE_RE.fullmatch(date) else None,
            practice_words=tuple(w for w in (words[:MAX_PRACTICE_WORDS] if isinstance(words, list) else []) if isinstance(w, str)),
        )


def spec_path(stem: str) -> Path:
    return get_tutoring_dir() / f"{stem}.job.json"


def write_spec(stem: str, spec: JobSpec) -> None:
    """입력을 파일로 남긴다. 쓰지 못해도 작업은 메모리 입력으로 돈다."""
    path = spec_path(stem)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(spec.to_json(), ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        logger.error("정리 작업 입력 저장 실패 %s: %s", path, e)


def read_spec(stem: str) -> Optional[JobSpec]:
    """남겨 둔 입력. 없거나 깨졌으면 None."""
    try:
        return JobSpec.from_json(json.loads(spec_path(stem).read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        logger.warning("정리 작업 입력을 읽지 못했어요 %s: %s", stem, e)
        return None


@dataclass
class Job:
    status: str = RUNNING
    result: Optional[dict] = None
    error: Optional[BaseException] = None
    observed: bool = False
    task: Optional["asyncio.Future"] = field(default=None, repr=False)


_JOBS: Dict[str, Job] = {}


def reset() -> None:
    """등록부를 비운다(시험용)."""
    _JOBS.clear()


def job_status(stem: str) -> str:
    """등록부 기준 상태: running|failed|done, 작업이 없으면 pending."""
    job = _JOBS.get(stem)
    return job.status if job else PENDING


def unfinished_status(stem: str) -> str:
    """요약 파일이 없는 통화의 상태: running|failed|pending. (파일이 저장되지 않은 done은 pending이다.)"""
    status = job_status(stem)
    return status if status in (RUNNING, FAILED) else PENDING


async def _run(job: Job, factory: Callable[[], Awaitable[dict]]) -> None:
    try:
        job.result = await factory()
        job.status = DONE
    except asyncio.CancelledError:
        job.status = FAILED
        job.error = RuntimeError("정리 작업이 중단되었습니다")
        raise
    except Exception as e:  # noqa: BLE001 - 합류한 요청이 같은 예외를 다시 올린다
        job.error = e
        job.status = FAILED


def _prune() -> None:
    finished = [stem for stem, job in _JOBS.items() if job.status != RUNNING]
    for stem in finished[: max(0, len(finished) - KEEP_FINISHED)]:
        del _JOBS[stem]


def start(stem: str, factory: Callable[[], Awaitable[dict]]) -> Job:
    """통화당 작업 하나: 돌고 있거나 끝난 작업이 있으면 그대로 돌려주고, 없거나 실패했으면 새로 건다.

    돌고 있는 이벤트 루프 안에서만 부른다.
    """
    job = _JOBS.get(stem)
    if job is not None and job.status in (RUNNING, DONE):
        return job
    job = Job()
    _JOBS[stem] = job
    job.task = asyncio.ensure_future(_run(job, factory))
    _prune()
    return job


async def wait(stem: str, factory: Callable[[], Awaitable[dict]]) -> dict:
    """작업을 걸거나 합류해 결과를 기다린다. 작업이 실패했으면 그 예외를 올린다.

    기다리는 요청이 끊겨도 작업은 이어 돈다(shield). 아무도 받지 못한 채 먼저 실패한 작업은 첫 요청이 그 실패를 받고
    (같은 통화를 곧바로 다시 돌리지 않는다), 그다음 요청부터는 새로 건다.
    """
    existing = _JOBS.get(stem)
    job = existing if existing is not None and existing.status == FAILED and not existing.observed else start(stem, factory)
    if job.status == RUNNING:
        await asyncio.shield(job.task)
    if job.error is not None:
        job.observed = True
        raise job.error
    assert job.result is not None
    return job.result
