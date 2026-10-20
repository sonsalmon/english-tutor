"""통화 주제에 맞는 유튜브 클립을 키워드로 찾는다(YouTube Data API v3 search.list).

구글로는 검색어(query)만 나간다. 한 번 검색에 쿼터 100유닛(하루 무료 10,000)이 들어서
통화(stem)마다 결과를 JSON으로 캐시하고, 같은 통화는 다시 검색하지 않는다. DB는 없다.
키 값은 로그·예외 문장에 절대 넣지 않는다.
"""

import html
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from server.history import _valid_stem

logger = logging.getLogger(__name__)

API_URL = "https://www.googleapis.com/youtube/v3/search"
KEY_ENV = "YOUTUBE_API_KEY"
KEY_FILE = Path("~/.config/english-tutor/youtube-api-key")
CLIPS_DIR_ENV = "CLIPS_DIR"
DEFAULT_CLIPS_DIR = "~/dev/learning/english/clips"
MAX_RESULTS = 5
# 제목에 이 낱말이 있으면 다른 언어 학습 영상으로 보고 버린다(영어 학습 영상은 남긴다).
OTHER_LANGUAGES = (
    "turkish", "spanish", "french", "german", "italian", "portuguese", "japanese", "chinese",
    "korean", "hindi", "arabic", "russian", "vietnamese", "indonesian", "thai",
)
_OTHER_LANG_RE = re.compile(r"\b(?:" + "|".join(OTHER_LANGUAGES) + r")\b", re.IGNORECASE)
TIMEOUT_SEC = 10

# http(url) -> (HTTP 상태 코드, 응답 본문 문자열). 테스트에서 가짜로 바꾼다.
HttpFn = Callable[[str], Tuple[int, str]]


class YouTubeError(RuntimeError):
    """검색 실패의 기본형. 메시지에는 키와 URL을 넣지 않는다."""


class YouTubeKeyMissing(YouTubeError):
    """API 키가 없다(환경변수도 키 파일도 없음)."""


class YouTubeQuotaError(YouTubeError):
    """하루 쿼터를 다 썼다(403 quotaExceeded 등)."""


class YouTubeHttpError(YouTubeError):
    """그 밖의 HTTP·네트워크·응답 형식 오류."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def api_key() -> Optional[str]:
    """YOUTUBE_API_KEY 환경변수, 없으면 키 파일. 둘 다 없거나 비면 None."""
    value = os.getenv(KEY_ENV, "").strip()
    if value:
        return value
    try:
        return KEY_FILE.expanduser().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def get_clips_dir() -> Path:
    return Path(os.getenv(CLIPS_DIR_ENV) or DEFAULT_CLIPS_DIR).expanduser()


def _default_http(url: str) -> Tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SEC) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        # e의 문자열에 URL(키 포함)이 섞일 수 있어 종류만 남긴다.
        raise YouTubeHttpError(f"네트워크 오류({type(e).__name__})") from None


def _error_reasons(body: str) -> List[str]:
    try:
        data = json.loads(body)
        errors = data["error"]["errors"]
        return [str(e.get("reason", "")) for e in errors if isinstance(e, dict)]
    except (ValueError, KeyError, TypeError):
        return []


def _thumbnail(snippet: Dict[str, Any]) -> str:
    thumbs = snippet.get("thumbnails")
    if not isinstance(thumbs, dict):
        return ""
    for name in ("medium", "high", "default"):
        entry = thumbs.get(name)
        if isinstance(entry, dict) and isinstance(entry.get("url"), str):
            return entry["url"]
    return ""


def _text(value: Any) -> str:
    return html.unescape(value).strip() if isinstance(value, str) else ""


def search(query: str, *, key: str, http: Optional[HttpFn] = None) -> List[Dict[str, str]]:
    """검색어로 영상 최대 5개를 찾아 {id,title,channel,thumbnail,published} 목록을 돌려준다."""
    params = {
        "part": "snippet",
        "type": "video",
        "maxResults": str(MAX_RESULTS),
        "relevanceLanguage": "en",
        "regionCode": "US",
        "safeSearch": "moderate",
        "videoEmbeddable": "true",
        "q": query,
        "key": key,
    }
    url = API_URL + "?" + urllib.parse.urlencode(params)
    status, body = (http or _default_http)(url)

    if status != 200:
        reasons = _error_reasons(body)
        if any(r in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded") for r in reasons):
            raise YouTubeQuotaError("유튜브 검색 쿼터를 다 썼습니다")
        raise YouTubeHttpError(f"유튜브 검색 실패(HTTP {status})", status)

    try:
        items = json.loads(body)["items"]
    except (ValueError, KeyError, TypeError):
        raise YouTubeHttpError("유튜브 응답 형식이 올바르지 않습니다", status) from None
    if not isinstance(items, list):
        raise YouTubeHttpError("유튜브 응답 형식이 올바르지 않습니다", status)

    clips: List[Dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        vid = item.get("id")
        video_id = vid.get("videoId") if isinstance(vid, dict) else None
        snippet = item.get("snippet")
        if not isinstance(video_id, str) or not video_id or not isinstance(snippet, dict):
            continue
        title = _text(snippet.get("title"))
        if _OTHER_LANG_RE.search(title):
            continue
        clips.append(
            {
                "id": video_id,
                "title": title,
                "channel": _text(snippet.get("channelTitle")),
                "thumbnail": _thumbnail(snippet),
                "published": _text(snippet.get("publishedAt")),
            }
        )
    return clips[:MAX_RESULTS]


def clips_for_call(
    stem: str,
    query: str,
    *,
    key: Optional[str] = None,
    http: Optional[HttpFn] = None,
) -> List[Dict[str, str]]:
    """통화(stem)의 클립 목록. 캐시(<CLIPS_DIR>/<stem>.json)가 있으면 검색 없이 돌려준다.

    stem이 통화 파일명 형식이 아니면 ValueError. 검색어가 비면 검색하지 않고 [].
    키가 없으면 YouTubeKeyMissing. 오류 결과는 캐시하지 않는다.
    """
    if not _valid_stem(stem):
        raise ValueError("허용되지 않은 통화 이름입니다")
    path = get_clips_dir() / f"{stem}.json"
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(cached, list):
            return cached
    except (OSError, ValueError):
        pass

    query = (query or "").strip()
    if not query:
        return []
    key = key or api_key()
    if not key:
        raise YouTubeKeyMissing("유튜브 API 키가 없습니다")

    clips = search(query, key=key, http=http)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(clips, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        logger.error("클립 캐시 저장 실패 %s: %s", path, e)
    return clips
