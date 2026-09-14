"""seok seok 채널 풀영상을 받아 내 킬 장면만 이어붙인 하이라이트를 만든다.

원본 .mkv 파일명에서 gameId·participantId 를 읽고,
Riot 타임라인으로 킬 시각만 가져온다.

예:
  python make_highlights.py 260911
  python make_highlights.py 2606911
  python make_highlights.py 260911 --list-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from api import get_kda_time_stamp, get_match_by_gameId  # noqa: E402
from youtube_video_source import get_videos_on_date  # noqa: E402

PRE_SEC = 15.0
POST_SEC = 3.0
CHAIN_GAP_SEC = 10.0
DEFAULT_LOADING_SEC = 3.0

KILL_KINDS = {"kill", "solo kill"}
MY_EVENT_KINDS = {"kill", "solo kill", "assist", "death"}

KEYSTONE_TITLE_ALIASES = {
    8230: "폭풍전사",
    8214: "콩콩이",
    8229: "유성",
    8437: "착취",
    8128: "어둠의 수확",
    8005: "집중 공격",
    8008: "치명적 속도",
    8021: "기민한 발놀림",
    8351: "빙결 강화",
    8360: "봉인 풀린 주문서",
}

_FREEZE_END_RE = re.compile(r"freezedetect.*freeze_end:\s*([\d.]+)")
_FREEZE_START_RE = re.compile(r"freezedetect.*freeze_start:\s*([\d.]+)")
_rune_ko_cache: dict[int, str] | None = None
_BAD = '<>:"/\\|?*'


def safe_name(name: str) -> str:
    return "".join("_" if c in _BAD else c for c in name).strip()


def normalize_date(raw: str) -> str:
    s = raw.strip()
    if s == "2606911":
        return "260911"
    if len(s) == 7 and s.startswith("260"):
        return "260" + s[4:]
    return s


def load_keystone_ko_names() -> dict[int, str]:
    global _rune_ko_cache
    if _rune_ko_cache is not None:
        return _rune_ko_cache
    url = "https://ddragon.leagueoflegends.com/cdn/16.1.1/data/ko_KR/runesReforged.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Highlight/1.0"})
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


def detect_intro_end(video_path: str, search_sec: float = 20.0) -> float | None:
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
    print(f"  [오프셋] 로딩 미감지 → 기본 {DEFAULT_LOADING_SEC:.1f}s")
    return DEFAULT_LOADING_SEC


def highlight_title(video: dict, keystone_name: str) -> str:
    """암베사 vs 나서스 폭풍전사 13 4 4 0914 01 GM1 1353"""
    date_str = str(video.get("date_str") or "")
    mmdd = date_str[2:] if len(date_str) == 6 else date_str
    game_no = int(video.get("game_number") or 0)
    my_champ = video.get("our_champion_name") or "나"
    opp = video.get("opponent_champion_name") or "상대"
    kills = int(video.get("kills") or 0)
    deaths = int(video.get("deaths") or 0)
    assists = int(video.get("assists") or 0)
    tier = (video.get("tier_full") or "").strip()
    parts = [my_champ, "vs", opp, keystone_name, str(kills), str(deaths), str(assists), mmdd, f"{game_no:02d}"]
    if tier:
        parts.append(tier)
    return " ".join(parts)


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
    stream = data["streams"][0]
    num, den = stream["r_frame_rate"].split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    duration = float(data.get("format", {}).get("duration") or 0)
    return {"width": int(stream["width"]), "height": int(stream["height"]), "fps": fps, "duration": duration}


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
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) < 1024:
        tail = (result.stderr or "")[-600:]
        raise RuntimeError(f"클립 자르기 실패 ({start:.2f}s, {duration:.2f}s): {tail}")


def concat_clips(paths: list[str], output_path: str) -> None:
    if not paths:
        raise ValueError("concat 할 클립이 없습니다.")
    if len(paths) == 1:
        os.replace(paths[0], output_path)
        return
    list_path = output_path + ".concat.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in paths:
            f.write(f"file '{p.replace(chr(92), '/')}'\n")
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-400:])
    finally:
        try:
            os.remove(list_path)
        except OSError:
            pass


def build_highlight(src: str, windows: list[tuple[float, float, list]], out_path: str) -> None:
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
        concat_clips(clips, out_path)
    finally:
        for p in clips:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        try:
            os.rmdir(work)
        except OSError:
            pass


def download_video(video_id: str, out_path: str) -> bool:
    import yt_dlp

    if os.path.exists(out_path) and os.path.getsize(out_path) > 8 * 1024 * 1024:
        print(f"  [다운] 이미 있음: {os.path.basename(out_path)}")
        return True
    opts = {
        "outtmpl": out_path,
        "merge_output_format": "mkv",
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "retries": 5,
        "noplaylist": True,
        "quiet": False,
        "noprogress": False,
    }
    print(f"  [다운] {video_id}")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    except Exception as e:
        print(f"  [다운] 실패: {e}")
        return False
    return os.path.exists(out_path) and os.path.getsize(out_path) > 1024 * 1024


def format_cluster(cluster: list[tuple[float, str]]) -> str:
    return ", ".join(f"{kind}@{t:.0f}s" for t, kind in cluster)


def process_one(v: dict, args, dl_dir: str, out_dir: str) -> bool:
    print(f"{v.get('file_name') or v.get('title')}")
    game_id = v.get("game_id")
    pid = v.get("participant_id")
    if not game_id or not pid:
        print("  [건너뜀] 원본 파일명에서 game_id 추출 실패")
        print(f"           현재 제목={v.get('title')!r}  fileName={v.get('file_name')!r}")
        return False
    print(f"  videoId={v['video_id']}  game_id={game_id}  pid={pid}  (출처: {v.get('id_source')})")

    try:
        events = my_timeline_events(game_id, int(pid))
        match = get_match_by_gameId(game_id)
        keystone_id = match_keystone_id(match, int(pid))
    except Exception as e:
        print(f"  [API] 타임라인/룬 실패: {e}")
        return False

    windows = cluster_kill_windows(events)
    keystone_name = keystone_title_name(keystone_id)
    out_name = safe_name(highlight_title(v, keystone_name)) + ".mkv"
    out_path = os.path.join(out_dir, out_name)

    print(f"  룬={keystone_name}  KDA={v.get('kills')}/{v.get('deaths')}/{v.get('assists')}  내 이벤트 {len(events)}개")
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

    dl_path = os.path.join(dl_dir, f"{v['video_id']}.mkv")
    if not download_video(v["video_id"], dl_path):
        return False

    offset = detect_game_offset(dl_path, args.offset)
    video_windows = [(s + offset, e + offset, c) for s, e, c in windows]
    try:
        build_highlight(dl_path, video_windows, out_path)
    except Exception as e:
        print(f"  [합성] 실패: {e}")
        return False

    size_mb = os.path.getsize(out_path) / (1024 ** 2)
    print(f"  [완료] {out_name}  ({size_mb:.1f} MB, 클립 {len(windows)}개)")
    if not args.keep_download:
        try:
            os.remove(dl_path)
        except OSError:
            pass
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="날짜별 롤 킬 하이라이트 생성")
    parser.add_argument("date", help="YYMMDD (예: 260911). 2606911 도 260911 로 처리")
    parser.add_argument("--scan", type=int, default=400, help="유튜브 최신순 스캔 상한")
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--offset", type=float, default=None)
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--keep-download", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    date_str = normalize_date(args.date)
    if date_str != args.date.strip():
        print(f"[날짜] {args.date} → {date_str} 로 보정")
    if not (len(date_str) == 6 and date_str.isdigit()):
        print("날짜는 YYMMDD 6자리로 입력하세요. 예: 260911")
        return 2

    work_dir = args.work_dir or os.path.join(ROOT, "highlights", date_str)
    dl_dir = os.path.join(args.work_dir or os.path.join(ROOT, "highlights"), "_download")
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(dl_dir, exist_ok=True)

    print(f"[DIR] 출력: {work_dir}")
    try:
        videos = get_videos_on_date(date_str, max_scan=args.scan)
    except FileNotFoundError as e:
        print(f"[오류] {e}")
        return 2
    print(f"[YT] {date_str} 원본 파일명 기준 {len(videos)}개")
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
