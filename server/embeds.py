"""영상별 임베드 가능 여부 캐시. 앱 안에서 틀 수 없는 영상은 피드와 예시 클립에서 뺀다.

- 모르는 영상 id는 YouTube Data API `videos?part=status`(status.embeddable)로 50개씩 묶어 한 번에 확인하고 캐시한다.
- 캐시는 자막 DB 밖의 JSON 파일이다(EMBED_CACHE_PATH, 기본은 자막 DB 옆 `embed-cache.json`). 자막 DB는 건드리지 않는다.
- 키가 없거나 호출이 실패하면 막히지 않은 것으로 보고 캐시하지 않는다(다음 요청에서 다시 확인한다).
  재생 중 오류는 클라이언트가 알려 주고(`mark_blocked`) 그 영상은 다음부터 빠진다.
- 키와 요청 주소는 로그에 남기지 않는다.
"""

import json
import logging
import os
import re
import threading
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from server import clipdb, youtube

logger = logging.getLogger(__name__)

PATH_ENV = "EMBED_CACHE_PATH"
API_URL = "https://www.googleapis.com/youtube/v3/videos"
BATCH = 50
ID_RE = re.compile(r"[A-Za-z0-9_-]{6,20}")

_LOCK = threading.Lock()


def cache_path() -> Path:
    override = os.getenv(PATH_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return clipdb.db_path().with_name("embed-cache.json")


def _http_get(url: str):
    return youtube._default_http(url)


def _load(path: Path) -> Dict[str, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    videos = data.get("videos") if isinstance(data, dict) else None
    return {k: v for k, v in videos.items() if isinstance(v, dict) and isinstance(v.get("embeddable"), bool)} if isinstance(videos, dict) else {}


def _save(path: Path, videos: Dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"version": 1, "videos": videos}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fetch_batch(ids: List[str], key: str) -> Optional[Dict[str, bool]]:
    """영상 id 최대 50개의 임베드 가능 여부. 응답에 없는 영상(삭제·비공개)은 False. 호출이 실패하면 None."""
    params = urllib.parse.urlencode({"part": "status", "id": ",".join(ids), "maxResults": len(ids), "key": key})
    try:
        status, body = _http_get(f"{API_URL}?{params}")
    except youtube.YouTubeError as e:
        logger.warning("임베드 가능 여부 조회 실패: %s", e)
        return None
    if status != 200:
        logger.warning("임베드 가능 여부 조회 실패: HTTP %s", status)
        return None
    try:
        items = json.loads(body)["items"]
    except (ValueError, KeyError, TypeError):
        logger.warning("임베드 가능 여부 조회 실패: 응답 형식")
        return None
    result = {i: False for i in ids}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or item.get("id") not in result:
            continue
        st = item.get("status") if isinstance(item.get("status"), dict) else {}
        result[item["id"]] = st.get("embeddable") is True and st.get("privacyStatus", "public") != "private"
    return result


def playable(ids: Iterable[str]) -> Set[str]:
    """ids 중 앱 안에서 틀 수 있는 영상 id 집합. 모르는 id는 이 호출에서 묶어서 한 번에 확인하고 캐시한다."""
    wanted = list(dict.fromkeys(i for i in ids if isinstance(i, str) and ID_RE.fullmatch(i)))
    if not wanted:
        return set()
    path = cache_path()
    with _LOCK:
        videos = _load(path)
        unknown = [i for i in wanted if i not in videos]
        key = youtube.api_key() if unknown else None
        if unknown and key:
            fresh: Dict[str, bool] = {}
            for start in range(0, len(unknown), BATCH):
                got = _fetch_batch(unknown[start : start + BATCH], key)
                if got is None:
                    break
                fresh.update(got)
            if fresh:
                stamp = _now()
                for vid, ok in fresh.items():
                    videos[vid] = {"embeddable": ok, "checked": stamp, "source": "api"}
                try:
                    _save(path, videos)
                except OSError as e:
                    logger.warning("임베드 캐시를 쓰지 못했습니다: %s", e)
    return {i for i in wanted if videos.get(i, {}).get("embeddable", True)}


def mark_blocked(video_id: str) -> bool:
    """클라이언트 플레이어가 오류를 낸 영상을 막힌 것으로 캐시한다. id 모양이 틀리면 False."""
    if not isinstance(video_id, str) or not ID_RE.fullmatch(video_id):
        return False
    path = cache_path()
    with _LOCK:
        videos = _load(path)
        videos[video_id] = {"embeddable": False, "checked": _now(), "source": "client"}
        _save(path, videos)
    return True
