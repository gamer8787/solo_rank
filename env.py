import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# 한국은 일광절약시간 없음. Windows 등에서 tzdata가 없으면 ZoneInfo 실패 → UTC+9 고정으로 동일 동작.

_KST_FALLBACK = timezone(timedelta(hours=9))


def _korea_tz():
    try:
        return ZoneInfo("Asia/Seoul")
    except ZoneInfoNotFoundError:
        return _KST_FALLBACK

# 공통 경로 설정
PROJECT_ROOT = r"C:\Users\seok\Desktop\youtube\auto_replay"

# 환경 변수 상수 설정
API_KEY = "RGAPI-632e0005-b179-47ca-9fca-a6ded837c09e"

# OBS WebSocket 설정
OBS_HOST = "localhost"
OBS_PORT = 4455
OBS_PASSWORD = "your_password"

# 모니터 설정 (2번 모니터가 왼쪽이면 2, 없으면 0이나 1로 조정 필요)
TARGET_MONITOR_INDEX = 2

# ---------------------------------------------------------
# [폴더 경로 설정]
# ---------------------------------------------------------
# 영상 저장 경로
VIDEO_FOLDER = r"C:\Users\seok\Videos\원본"      # OBS가 저장하는 곳
NEW_VIDEO_FOLDER = r"C:\Users\seok\Videos\솔랭"  # 솔로/듀오 랭크 저장
FLEX_RANK_VIDEO_FOLDER = r"C:\Users\seok\Videos\자유랭"  # 자유랭(플렉스) 저장 — 트림 동일
ETC_VIDEO_FOLDER = r"C:\Users\seok\Videos\etc"   # 그 외 저장할 곳
HIGHLIGHT_VIDEO_FOLDER = r"C:\Users\seok\Videos\하이라이트"  # 킬 하이라이트 출력

# ---------------------------------------------------------
# Data Dragon — 패치 일정 & CDN
# ---------------------------------------------------------
# Riot 예정 패치일(캡처 기준). 한국 표준시(KST, Asia/Seoul) 해당 날짜 12:00 이후부터 그 패치 구간 버전 사용.
PATCH_SCHEDULE_DATES = [
    (2026, 1, 8),
    (2026, 1, 22),
    (2026, 2, 4),
    (2026, 2, 19),
    (2026, 3, 4),
    (2026, 3, 18),
    (2026, 4, 1),
    (2026, 4, 15),
    (2026, 4, 29),
    (2026, 5, 13),
    (2026, 5, 28),
    (2026, 6, 10),
    (2026, 6, 24),
    (2026, 7, 15),
    (2026, 7, 29),
    (2026, 8, 12),
    (2026, 8, 26),
    (2026, 9, 10),
    (2026, 9, 23),
    (2026, 10, 7),
    (2026, 10, 21),
    (2026, 11, 4),
    (2026, 11, 18),
    (2026, 12, 9),
]

# PATCH_SCHEDULE_DATES와 동일한 길이·순서. None이면 https://ddragon.../api/versions.json 의 최상단 버전 사용
PATCH_VERSION_HINTS = ["16.1.1"] + [None] * (len(PATCH_SCHEDULE_DATES) - 1)

# 26.01(첫 일정) KST 12:00 이전에 쓸 Data Dragon 버전
PRE_SCHEDULE_DATA_DRAGON_VERSION = "16.1.1"

DDRAGON_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AutoReplay/1.0"

_versions_cache_time: float = 0.0
_versions_cache_list: list[str] | None = None


def _fetch_versions_list() -> list[str]:
    url = "https://ddragon.leagueoflegends.com/api/versions.json"
    req = urllib.request.Request(url, headers={"User-Agent": DDRAGON_USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_versions_list() -> list[str]:
    global _versions_cache_time, _versions_cache_list
    now = time.time()
    if _versions_cache_list is None or (now - _versions_cache_time) > 3600:
        _versions_cache_list = _fetch_versions_list()
        _versions_cache_time = now
    return _versions_cache_list


def get_data_dragon_version() -> str:
    tz = _korea_tz()
    now = datetime.now(tz)
    idx = -1
    for i, (y, mo, d) in enumerate(PATCH_SCHEDULE_DATES):
        noon = datetime(y, mo, d, 12, 0, 0, tzinfo=tz)
        if noon <= now:
            idx = i
        else:
            break
    if idx < 0:
        return PRE_SCHEDULE_DATA_DRAGON_VERSION
    if idx < len(PATCH_VERSION_HINTS) and PATCH_VERSION_HINTS[idx]:
        return PATCH_VERSION_HINTS[idx]
    return _get_versions_list()[0]


def ddragon_versioned_cdn_root() -> str:
    return f"https://ddragon.leagueoflegends.com/cdn/{get_data_dragon_version()}"


def ddragon_unversioned_img_root() -> str:
    return "https://ddragon.leagueoflegends.com/cdn/img"


FONT_PATH = os.path.join(PROJECT_ROOT, "font", "Anton-Regular.ttf")

CHANNEL_ID = "UCiEE8IL4brsmIHHViLnRvYw"

OPEN_VIDEO = True
FEEDBACK = False
MAX_RETRIES = 5
