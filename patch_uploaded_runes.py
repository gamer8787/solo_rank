"""업로드된 영상을 yt-dlp 로 받아 룬 오버레이를 끼워 넣는다 (업로드는 하지 않음).

예:
  python patch_uploaded_runes.py --count 3
  python patch_uploaded_runes.py --since 260822 --champion 암베사 --keystone 8230
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from api import get_match_by_gameId  # noqa: E402
from modules.rune_overlay import save_rune_overlay_png  # noqa: E402
from modules.rune_patch import add_rune_overlay  # noqa: E402
from youtube_video_source import get_recent_videos, get_videos_since  # noqa: E402

YTDLP = r"C:\Users\seok\Desktop\유튜브\yt-dlp.exe"
WORK_ROOT = r"C:\Users\seok\Videos\룬추가"

# 1080p DASH 우선. HLS(~) 는 추정 비트레이트라 가끔 저화질로 떨어진다.
FORMAT = (
    "bestvideo[height>=1080][protocol^=http]+bestaudio[protocol^=http]/"
    "bestvideo[height>=1080]+bestaudio/"
    "bv*[height>=720][protocol^=http]+ba[protocol^=http]/"
    "bv*+ba/b"
)

# 1080p60 유튜브 재인코딩본은 보통 분당 25MB 이상. 이하면 실패한 다운로드로 본다.
MIN_BYTES_PER_SEC = 200_000
MIN_ABS_BYTES = 80 * 1024 * 1024

# 폭풍전사의 포효 (구 난입과 동일 ID)
KEYSTONE_STORMRAIDER = 8230

_BAD = '<>:"/\\|?*'


def safe_name(name: str) -> str:
    return "".join("_" if c in _BAD else c for c in name).strip()


def output_stem(video: dict) -> str:
    return safe_name(os.path.splitext(video.get("file_name") or "")[0] or video["title"])


def file_looks_ok(path: str) -> bool:
    if not os.path.exists(path):
        return False
    size = os.path.getsize(path)
    if size < MIN_ABS_BYTES:
        return False
    try:
        raw = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            text=True,
            encoding="utf-8",
        ).strip()
        duration = float(raw)
    except (subprocess.CalledProcessError, ValueError):
        return size >= MIN_ABS_BYTES
    return size >= max(MIN_ABS_BYTES, duration * MIN_BYTES_PER_SEC * 0.4)


def download(video_id: str, out_path: str, cookies_from_browser: str | None, cookies_file: str | None) -> bool:
    if file_looks_ok(out_path):
        print(f"  [다운] 이미 있음, 건너뜀: {os.path.basename(out_path)}")
        return True
    if os.path.exists(out_path):
        print(f"  [다운] 기존 파일이 너무 작음 → 다시 받음 ({os.path.getsize(out_path)} bytes)")
        try:
            os.remove(out_path)
        except OSError:
            pass

    cmd = [
        YTDLP,
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
    if not file_looks_ok(out_path):
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


def build_rune_png(game_id: str, participant_id: int, png_path: str) -> str | None:
    data = get_match_by_gameId(game_id)
    if not data:
        print(f"  [룬] 매치 조회 실패: {game_id}")
        return None
    try:
        participant = data["info"]["participants"][participant_id - 1]
    except (KeyError, IndexError):
        print(f"  [룬] participant {participant_id} 없음")
        return None
    print(f"  [룬] {participant['championName']} (participant {participant_id})")
    return save_rune_overlay_png(participant, png_path)


def participant_perk_ids(match: dict, participant_id: int) -> list[int]:
    p = match["info"]["participants"][participant_id - 1]
    ids: list[int] = []
    for style in p["perks"]["styles"]:
        for sel in style["selections"]:
            ids.append(int(sel["perk"]))
    return ids


def filter_by_runes(
    videos: list[dict],
    keystone_id: int | None = None,
    required: list[int] | None = None,
) -> list[dict]:
    required = required or []
    kept: list[dict] = []
    for i, v in enumerate(videos, 1):
        try:
            match = get_match_by_gameId(v["game_id"])
            perks = participant_perk_ids(match, v["participant_id"])
            champ = match["info"]["participants"][v["participant_id"] - 1]["championName"]
        except Exception as e:
            print(f"  [필터] {v.get('title')} 매치 조회 실패: {e}")
            time.sleep(1.2)
            continue
        kid = perks[0] if perks else None
        ok = True
        if keystone_id is not None and kid != keystone_id:
            ok = False
        if any(rid not in perks for rid in required):
            ok = False
        mark = "O" if ok else "X"
        extra = f" perks={perks}" if ok or required else ""
        print(f"  [{i}/{len(videos)}] {mark} {v['date_str']} #{v.get('game_number')} {v.get('our_champion_name')}  "
              f"keystone={kid} champ={champ}{extra}  {v['game_id']}")
        if ok:
            kept.append(v)
        time.sleep(1.2)
    return kept


def collect_videos(args) -> list[dict]:
    if args.since:
        videos = get_videos_since(args.since, max_scan=args.scan)
        print(f"[API] {args.since} 이후 {len(videos)}개")
    else:
        videos = get_recent_videos(args.count)
        print(f"[API] 최근 {len(videos)}개")

    if args.champion:
        before = len(videos)
        videos = [v for v in videos if v.get("our_champion_name") == args.champion]
        print(f"[필터] 챔피언 '{args.champion}': {before} → {len(videos)}")

    if args.keystone is not None or args.has_rune:
        print(f"[필터] 룬 조회 중... keystone={args.keystone} has={args.has_rune}")
        videos = filter_by_runes(videos, args.keystone, args.has_rune)
        print(f"[필터] 룬 일치 {len(videos)}개")
    return videos


def process_one(v: dict, work_dir: str, dl_dir: str, png_dir: str, args) -> bool:
    print(f"{v['title']}  ({v['privacy']}, {v['duration']})")
    if not v.get("game_id"):
        print("  [건너뜀] game_id 추출 실패")
        return False
    print(f"  videoId={v['video_id']}  game_id={v['game_id']}  pid={v['participant_id']}")

    stem = output_stem(v)
    dl_path = os.path.join(dl_dir, f"{stem}.mkv")
    out_path = os.path.join(work_dir, f"{stem}.mkv")

    if file_looks_ok(out_path) and not args.force:
        print(f"  [건너뜀] 결과물 이미 있음 ({os.path.getsize(out_path) / (1024 ** 3):.2f} GB)")
        return True

    cookies_browser = args.cookies_from_browser
    if v.get("privacy") == "private" and not cookies_browser and not args.cookies:
        cookies_browser = "edge"

    if not download(v["video_id"], dl_path, cookies_browser, args.cookies):
        if v.get("privacy") == "private" and cookies_browser != "chrome" and not args.cookies:
            print("  [다운] edge 실패 → chrome 쿠키 재시도")
            if download(v["video_id"], dl_path, "chrome", None):
                pass
            else:
                return False
        else:
            return False

    png_path = os.path.join(png_dir, f"{v['game_id']}_{v['participant_id']}.png")
    rune_png = build_rune_png(v["game_id"], v["participant_id"], png_path)
    if not rune_png:
        return False

    try:
        info = add_rune_overlay(dl_path, out_path, rune_png)
    except Exception as e:
        print(f"  [합성] 실패: {e}")
        return False

    if not file_looks_ok(out_path):
        print(f"  [합성] 결과 파일 이상 ({os.path.getsize(out_path) if os.path.exists(out_path) else 0} bytes)")
        return False

    size_gb = os.path.getsize(out_path) / (1024 ** 3)
    print(f"  [완료] {os.path.basename(out_path)}  ({size_gb:.2f} GB, 룬 {info['rune_start']:.2f}~{info['rune_end']:.2f}s)")
    if not args.keep_download:
        try:
            os.remove(dl_path)
        except OSError:
            pass
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="업로드 영상에 룬 오버레이 추가")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--since", help="YYMMDD 이상만 (예: 260822 = 최근 3주)")
    parser.add_argument("--scan", type=int, default=400, help="since 사용 시 최신순 스캔 상한")
    parser.add_argument("--champion", help="내 챔피언 한글명 (예: 암베사)")
    parser.add_argument("--keystone", type=int, help=f"핵심 룬 ID (폭풍전사={KEYSTONE_STORMRAIDER})")
    parser.add_argument(
        "--has-rune",
        type=int,
        action="append",
        default=[],
        help="추가로 들어 있어야 하는 룬 ID (반복 가능, 예: 돌발일격=8143)",
    )
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--cookies-from-browser", default=None, help="예: chrome, edge")
    parser.add_argument("--cookies", default=None)
    parser.add_argument("--keep-download", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    work_dir = args.work_dir or WORK_ROOT
    dl_dir = os.path.join(work_dir, "_download")
    png_dir = os.path.join(work_dir, "_rune_png")
    for d in (work_dir, dl_dir, png_dir):
        os.makedirs(d, exist_ok=True)

    print(f"[DIR] 작업 폴더: {work_dir}")
    videos = collect_videos(args)
    print()

    if args.list_only:
        for i, v in enumerate(videos, 1):
            print(f"[{i}] {v['date_str']} {v.get('game_number')} {v['title']}  {v['privacy']}  {v['video_id']}")
        print(f"총 {len(videos)}개")
        return 0

    ok = fail = 0
    for i, v in enumerate(videos, 1):
        print("=" * 70)
        print(f"[{i}/{len(videos)}] ", end="")
        if process_one(v, work_dir, dl_dir, png_dir, args):
            ok += 1
        else:
            fail += 1
        print()

    print("=" * 70)
    print(f"[DONE] 성공 {ok}개 / 실패 {fail}개 → {work_dir}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
