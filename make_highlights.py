"""seok seok 채널 풀영상을 yt-dlp 로 받아 내 킬 장면만 이어붙인 하이라이트를 만든다.

예:
  python make_highlights.py 260913
  python make_highlights.py 260913 --list-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from api import get_kda_time_stamp, get_match_by_gameId  # noqa: E402
from env import (  # noqa: E402
    DDRAGON_USER_AGENT,
    HIGHLIGHT_VIDEO_FOLDER,
    ddragon_versioned_cdn_root,
)
from youtube_video_source import get_videos_on_date  # noqa: E402

PRE_SEC = 15.0
POST_SEC = 3.0
CHAIN_GAP_SEC = 10.0
DEFAULT_LOADING_SEC = 3.0

KILL_KINDS = {"kill", "solo kill"}
MY_EVENT_KINDS = {"kill", "solo kill", "assist", "death"}

YTDLP = r"C:\Users\seok\Desktop\유튜브\yt-dlp.exe"
FORMAT = (
    "bestvideo[height>=1080][protocol^=http]+bestaudio[protocol^=http]/"
    "bestvideo[height>=1080]+bestaudio/"
    "bv*[height>=720][protocol^=http]+ba[protocol^=http]/"
    "bv*+ba/b"
)

_BAD = '<>:"/\\|?*'
_FREEZE_END_RE = re.compile(r"freezedetect.*freeze_end:\s*([\d.]+)")
_FREEZE_START_RE = re.compile(r"freezedetect.*freeze_start:\s*([\d.]+)")

# 제목에 쓰기 좋은 짧은 한글명. 없으면 Data Dragon 한글명 그대로.
KEYSTONE_TITLE_ALIASES = {
    8005: "집중 공격",
    8008: "치명적 속도",
    8010: "정복자",
    8021: "기민한 발놀림",
    8112: "감전",
    8128: "어둠의 수확",
    8214: "콩콩이",
    8229: "유성",
    8230: "폭풍전사",
    8351: "빙결 강화",
    8360: "봉인 풀린 주문서",
    8369: "선제공격",
    8437: "착취",
    8439: "여진",
    8465: "수호자",
    9923: "칼날비",
}

_rune_ko_cache: dict[int, str] | None = None


def safe_name(name: str) -> str:
    return "".join("_" if c in _BAD else c for c in name).strip()


def yt_dlp_bin() -> str:
    if os.path.isfile(YTDLP):
        return YTDLP
    found = shutil.which("yt-dlp")
    if found:
        return found
    raise FileNotFoundError("yt-dlp 를 찾을 수 없습니다.")


def load_keystone_ko_names() -> dict[int, str]:
    global _rune_ko_cache
    if _rune_ko_cache is not None:
        return _rune_ko_cache
    url = f"{ddragon_versioned_cdn_root()}/data/ko_KR/runesReforged.json"
    req = urllib.request.Request(url, headers={"User-Agent": DDRAGON_USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        trees = json.loads(resp.read().decode("utf-8"))
    names: dict[int, str] = {}
    for tree in trees:
        for slot in tree.get("slots", []):
            for rune in slot.get("runes", []):
                names[int(rune["id"])] = rune["name"]
    _rune_ko_cache = names
    return names


def keystone_title_name(rune_id: int) -> str:
    if rune_id in KEYSTONE_TITLE_ALIASES:
        return KEYSTONE_TITLE_ALIASES[rune_id]
    return load_keystone_ko_names().get(rune_id, str(rune_id))


def parse_kda(video: dict) -> tuple[int, int, int]:
    raw = video.get("kda_str") or ""
    parts = raw.replace("_", " ").split()
    if len(parts) >= 3:
        return int(parts[0]), int(parts[1]), int(parts[2])
    return 0, 0, 0


def my_timeline_events(game_id: str, participant_id: int) -> list[tuple[float, str]]:
    rows = get_kda_time_stamp(game_id, participant_id)
    events = [(float(sec), kind) for sec, kind, _x, _y in rows if kind in MY_EVENT_KINDS]
    events.sort(key=lambda e: e[0])
    return events


def cluster_kill_windows(
    events: list[tuple[float, str]],
    *,
    pre_sec: float = PRE_SEC,
    post_sec: float = POST_SEC,
    gap_sec: float = CHAIN_GAP_SEC,
) -> list[tuple[float, float, list[tuple[float, str]]]]:
    """킬이 들어 있는 연속 이벤트(간격 <= gap)를 하나의 구간으로 묶는다.

    - 시작: 클러스터 첫 이벤트 - 15초 (어시스트 후 킬이면 어시스트 앞 15초)
    - 끝: 클러스터 마지막 이벤트 + 3초
    """
    if not events:
        return []

    clusters: list[list[tuple[float, str]]] = []
    current = [events[0]]
    for ev in events[1:]:
        if ev[0] - current[-1][0] <= gap_sec:
            current.append(ev)
        else:
            clusters.append(current)
            current = [ev]
    clusters.append(current)

    windows: list[tuple[float, float, list[tuple[float, str]]]] = []
    for cluster in clusters:
        if not any(kind in KILL_KINDS for _t, kind in cluster):
            continue
        start = max(0.0, cluster[0][0] - pre_sec)
        end = cluster[-1][0] + post_sec
        windows.append((start, end, cluster))

    merged: list[tuple[float, float, list[tuple[float, str]]]] = []
    for start, end, cluster in windows:
        if merged and start <= merged[-1][1]:
            p_start, p_end, p_cluster = merged[-1]
            merged[-1] = (p_start, max(p_end, end), p_cluster + cluster)
        else:
            merged.append((start, end, cluster))
    return merged


def detect_intro_end(video_path: str, search_sec: float = 12.0) -> float | None:
    """머리쪽 로딩 정지프레임이 끝나는 시각. 못 찾으면 None."""
    cmd = [
        "ffmpeg", "-v", "info",
        "-t", f"{search_sec:.3f}",
        "-i", video_path,
        "-vf", "freezedetect=n=-60dB:d=0.5",
        "-map", "0:v:0",
        "-f", "null", os.devnull,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = (proc.stderr or "") + (proc.stdout or "")
    starts = [float(m) for m in _FREEZE_START_RE.findall(log)]
    ends = [float(m) for m in _FREEZE_END_RE.findall(log)]
    if not starts or not ends:
        return None
    if starts[0] > 0.5:
        return None
    return ends[0]


def detect_game_offset(video_path: str, override: float | None) -> float:
    if override is not None:
        print(f"  [오프셋] 지정값 {override:.2f}s")
        return max(0.0, override)

    intro_end = detect_intro_end(video_path)
    if intro_end is not None and intro_end >= 0.8:
        print(f"  [오프셋] 로딩 정지프레임 {intro_end:.2f}s")
        return intro_end

    print(f"  [오프셋] 로딩 미감지 → 기본 {DEFAULT_LOADING_SEC:.1f}s (바로 시작이면 --offset 0)")
    return DEFAULT_LOADING_SEC


def highlight_title(video: dict, keystone_name: str, kills: int, deaths: int, assists: int) -> str:
    date_str = str(video.get("date_str") or "")
    mmdd = date_str[2:] if len(date_str) == 6 else date_str
    game_no = int(video.get("game_number") or 0)
    my_champ = video.get("our_champion_name") or "나"
    opp = video.get("opponent_champion_name") or "상대"
    return f"{my_champ} vs {opp} {keystone_name} {kills} {deaths} {assists} {mmdd} {game_no:02d}"


def match_keystone_id(match: dict, participant_id: int) -> int:
    p = match["info"]["participants"][participant_id - 1]
    return int(p["perks"]["styles"][0]["selections"][0]["perk"])


def probe_video(path: str) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate:format=duration",
        "-of", "json",
        path,
    ]
    raw = subprocess.check_output(cmd, text=True, encoding="utf-8")
    data = json.loads(raw)
    stream = (data.get("streams") or [{}])[0]
    rate = str(stream.get("r_frame_rate") or "60/1")
    num, _, den = rate.partition("/")
    fps = float(num) / float(den or 1)
    return {
        "width": int(stream.get("width") or 1920),
        "height": int(stream.get("height") or 1080),
        "fps": fps,
        "duration": float((data.get("format") or {}).get("duration") or 0),
    }


def cut_clip(src: str, dst: str, start: float, duration: float) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", src,
        "-t", f"{duration:.3f}",
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-avoid_negative_ts", "make_zero",
        dst,
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) < 1024:
        tail = (result.stderr or "")[-600:]
        raise RuntimeError(f"클립 자르기 실패 ({start:.2f}s, {duration:.2f}s): {tail}")


def _concat_file_line(path: str) -> str:
    p = os.path.abspath(path).replace("\\", "/").replace("'", "'\\''")
    return f"file '{p}'"


def concat_clip_list(paths: list[str], output_path: str) -> None:
    if not paths:
        raise ValueError("concat 할 클립이 없습니다.")
    if len(paths) == 1:
        shutil.copy2(paths[0], output_path)
        return

    list_path = output_path + ".concat.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        f.write("\n".join(_concat_file_line(p) for p in paths) + "\n")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        output_path,
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        os.remove(list_path)
    except OSError:
        pass
    if result.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
        tail = (result.stderr or "")[-600:]
        raise RuntimeError(f"클립 이어붙이기 실패: {tail}")


def build_highlight(src: str, windows: list[tuple[float, float, list]], out_path: str) -> None:
    if not windows:
        raise ValueError("자를 킬 구간이 없습니다.")

    meta = probe_video(src)
    duration = float(meta.get("duration") or 0)

    work = tempfile.mkdtemp(prefix="highlight_")
    clips: list[str] = []
    try:
        for i, (start, end, _cluster) in enumerate(windows, 1):
            start = max(0.0, start)
            end = min(duration, end) if duration else end
            if end - start < 0.4:
                print(f"    [클립 {i}] 너무 짧음 건너뜀 {start:.1f}-{end:.1f}")
                continue
            clip_path = os.path.join(work, f"clip_{i:02d}.mkv")
            print(f"    [클립 {i}/{len(windows)}] {start:.1f}s ~ {end:.1f}s  ({end - start:.1f}s)")
            cut_clip(src, clip_path, start, end - start)
            clips.append(clip_path)

        if not clips:
            raise RuntimeError("유효한 클립이 없습니다.")
        concat_clip_list(clips, out_path)
    finally:
        for p in clips:
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(work)
        except OSError:
            pass


def format_cluster(cluster: list[tuple[float, str]]) -> str:
    return ", ".join(f"{kind}@{t:.0f}s" for t, kind in cluster)


def download(video_id: str, out_path: str, cookies_from_browser: str | None, cookies_file: str | None) -> bool:
    if os.path.exists(out_path) and os.path.getsize(out_path) > 80 * 1024 * 1024:
        print(f"  [다운] 이미 있음, 건너뜀: {os.path.basename(out_path)}")
        return True
    if os.path.exists(out_path):
        print(f"  [다운] 기존 파일이 너무 작음 → 다시 받음 ({os.path.getsize(out_path)} bytes)")
        try:
            os.remove(out_path)
        except OSError:
            pass

    cmd = [
        yt_dlp_bin(),
        "-f", FORMAT,
        "-S", "res:1080,fps,br",
        "--merge-output-format", "mkv",
        "--retries", "5",
        "--no-playlist",
        "--newline",
        "-o", out_path,
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    extra: list[str] = []
    if cookies_from_browser:
        extra += ["--cookies-from-browser", cookies_from_browser]
    if cookies_file:
        extra += ["--cookies", cookies_file]
    cmd[1:1] = extra

    print(f"  [다운] {video_id} → {os.path.basename(out_path)}")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        print(f"  [다운] 실패: {tail[-1] if tail else '알 수 없는 오류'}")
        return False
    if not os.path.exists(out_path) or os.path.getsize(out_path) < 20 * 1024 * 1024:
        size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
        print(f"  [다운] 화질 이상 ({size / (1024 ** 2):.1f} MB) → 폐기")
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
        return False
    print(f"  [다운] {os.path.getsize(out_path) / (1024 ** 3):.2f} GB")
    return True


def resolve_source(v: dict, args, dl_dir: str) -> str | None:
    video_id = v.get("video_id")
    if not video_id:
        print("  [건너뜀] video_id 없음 (유튜브 목록 필요)")
        return None

    stem = safe_name(os.path.splitext(v.get("file_name") or "")[0] or v.get("title") or video_id)
    dl_path = os.path.join(dl_dir, f"{stem}.mkv")

    cookies_browser = args.cookies_from_browser
    if v.get("privacy") == "private" and not cookies_browser and not args.cookies:
        cookies_browser = "edge"

    if download(video_id, dl_path, cookies_browser, args.cookies):
        return dl_path
    if v.get("privacy") == "private" and cookies_browser != "chrome" and not args.cookies:
        print("  [다운] edge 실패 → chrome 쿠키 재시도")
        if download(video_id, dl_path, "chrome", None):
            return dl_path
    return None


def process_one(v: dict, args, dl_dir: str, out_dir: str) -> bool:
    title = v.get("title") or ""
    print(f"{title}  ({v.get('privacy')}, {v.get('duration')})")
    if not v.get("game_id"):
        print("  [건너뜀] game_id 추출 실패")
        return False

    game_id = v["game_id"]
    pid = int(v.get("participant_id") or 1)
    print(f"  videoId={v.get('video_id')}  game_id={game_id}  pid={pid}")

    try:
        events = my_timeline_events(game_id, pid)
        match = get_match_by_gameId(game_id)
        keystone_id = match_keystone_id(match, pid)
        me = match["info"]["participants"][pid - 1]
        kills, deaths, assists = int(me["kills"]), int(me["deaths"]), int(me["assists"])
    except Exception as e:
        print(f"  [API] 매치/타임라인 실패: {e}")
        return False

    windows = cluster_kill_windows(events)
    keystone_name = keystone_title_name(keystone_id)
    out_name = safe_name(highlight_title(v, keystone_name, kills, deaths, assists)) + ".mkv"
    out_path = os.path.join(out_dir, out_name)

    print(f"  룬={keystone_name}({keystone_id})  KDA={kills}/{deaths}/{assists}  내 이벤트 {len(events)}개")
    if not windows:
        print("  [건너뜀] 킬 없음")
        return True

    for i, (start, end, cluster) in enumerate(windows, 1):
        print(f"    구간 {i}: 게임 {start:.1f}~{end:.1f}s  [{format_cluster(cluster)}]")

    if args.list_only:
        print(f"  [목록] {out_name}")
        return True

    if os.path.exists(out_path) and os.path.getsize(out_path) > 100_000 and not args.force:
        print(f"  [건너뜀] 결과물 이미 있음 ({os.path.getsize(out_path) / (1024 ** 2):.1f} MB)")
        return True

    src = resolve_source(v, args, dl_dir)
    if not src:
        return False

    offset = detect_game_offset(src, args.offset)
    video_windows = [
        (start + offset, end + offset, cluster)
        for start, end, cluster in windows
    ]

    try:
        build_highlight(src, video_windows, out_path)
    except Exception as e:
        print(f"  [합성] 실패: {e}")
        return False

    size_mb = os.path.getsize(out_path) / (1024 ** 2)
    print(f"  [완료] {out_name}  ({size_mb:.1f} MB, 클립 {len(windows)}개)")

    downloaded = os.path.abspath(os.path.dirname(src)) == os.path.abspath(dl_dir)
    if downloaded and not args.keep_download:
        try:
            os.remove(src)
        except OSError:
            pass
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="날짜별 롤 킬 하이라이트 생성")
    parser.add_argument("date", help="YYMMDD (예: 260913)")
    parser.add_argument("--scan", type=int, default=400, help="유튜브 최신순 스캔 상한")
    parser.add_argument("--list-only", action="store_true", help="다운로드/자르기 없이 구간만 출력")
    parser.add_argument("--offset", type=float, default=None, help="게임 시작 오프셋(초). 생략 시 로딩 자동 감지")
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--cookies-from-browser", default=None, help="예: chrome, edge")
    parser.add_argument("--cookies", default=None)
    parser.add_argument("--keep-download", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    date_str = args.date.strip()
    if not (len(date_str) == 6 and date_str.isdigit()):
        print("날짜는 YYMMDD 6자리로 입력하세요. 예: 260913")
        return 2

    work_dir = args.work_dir or os.path.join(HIGHLIGHT_VIDEO_FOLDER, date_str)
    dl_dir = os.path.join(args.work_dir or HIGHLIGHT_VIDEO_FOLDER, "_download")
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(dl_dir, exist_ok=True)

    print(f"[DIR] 출력: {work_dir}")
    try:
        videos = get_videos_on_date(date_str, max_scan=args.scan)
    except FileNotFoundError as e:
        print(f"[YouTube] {e}")
        return 2
    print(f"[대상] {date_str} 영상 {len(videos)}개")
    print()

    if not videos:
        print("해당 날짜 영상이 없습니다.")
        return 0

    ok = fail = 0
    for i, v in enumerate(videos, 1):
        print("=" * 70)
        print(f"[{i}/{len(videos)}] ", end="")
        if process_one(v, args, dl_dir, work_dir):
            ok += 1
        else:
            fail += 1
        print()

    print("=" * 70)
    print(f"[DONE] 성공 {ok}개 / 실패 {fail}개 → {work_dir}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
