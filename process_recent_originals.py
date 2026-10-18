"""원본 폴더 최근 N개를 종료 시각으로 매치 매칭 후 솔랭 재편집."""

from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import re
import sys

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from env import API_KEY, NEW_VIDEO_FOLDER, VIDEO_FOLDER  # noqa: E402
from modules.video_manager import SOLO_DUO_QUEUE_ID, VideoManager  # noqa: E402


def pick_originals(count: int) -> list[str]:
    paths: list[str] = []
    for ext in ("*.mkv", "*.mp4"):
        paths.extend(glob.glob(os.path.join(VIDEO_FOLDER, ext)))
    paths.sort(key=os.path.getmtime)
    return paths[-count:]


def fetch_solo_matches_for_puuids(puuids: set[str], since_ts: float) -> list[tuple[str, str, float, float]]:
    matches: list[tuple[str, str, float, float]] = []
    seen: set[str] = set()
    for puuid in puuids:
        r = requests.get(
            f"https://asia.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids",
            params={"start": 0, "count": 20},
            headers={"X-Riot-Token": API_KEY},
            timeout=30,
        )
        if r.status_code != 200:
            continue
        for mid in r.json():
            if mid in seen:
                continue
            seen.add(mid)
            mr = requests.get(
                f"https://asia.api.riotgames.com/lol/match/v5/matches/{mid}",
                headers={"X-Riot-Token": API_KEY},
                timeout=30,
            )
            if mr.status_code != 200:
                continue
            info = mr.json()["info"]
            if info.get("queueId") != SOLO_DUO_QUEUE_ID:
                continue
            me = next((p for p in info["participants"] if p["puuid"] in puuids), None)
            if not me:
                continue
            ge = info["gameEndTimestamp"] / 1000
            gs = info["gameStartTimestamp"] / 1000
            if ge < since_ts:
                continue
            matches.append((str(info["gameId"]), me["championName"], gs, ge))
    return matches


def match_game_id(rec_end: float, matches: list[tuple[str, str, float, float]]) -> str | None:
    if not matches:
        return None
    best = min(matches, key=lambda x: abs(x[3] - rec_end))
    if abs(best[3] - rec_end) > 600:
        return None
    return best[0]


def remove_existing_game_files(work_dir: str, date_prefix: str, orders: list[int]) -> None:
    for path in glob.glob(os.path.join(work_dir, f"{date_prefix} *.mkv")):
        name = os.path.basename(path)
        m = re.match(r"^\d{6}\s+(\d{2})\s", name)
        if m and int(m.group(1)) in orders:
            os.remove(path)
            print(f"[DEL] {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="원본 최근 N개 솔랭 재편집")
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--work-dir", default=None, help="미지정 시 솔랭/YYMMDD")
    parser.add_argument("--start-order", type=int, default=1)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    originals = pick_originals(args.count)
    if len(originals) < args.count:
        print(f"[ERROR] 원본 {args.count}개 부족 (발견 {len(originals)})")
        return 1

    with open("puuid_list.json", encoding="utf-8") as f:
        puuids = set(json.load(f))

    since_ts = VideoManager.get_recording_times_from_file(originals[0])[0] - 7200
    matches = fetch_solo_matches_for_puuids(puuids, since_ts)

    date_str = datetime.datetime.fromtimestamp(
        VideoManager.get_recording_times_from_file(originals[-1])[1]
    ).strftime("%y%m%d")
    work_dir = args.work_dir or os.path.join(NEW_VIDEO_FOLDER, date_str)
    os.makedirs(work_dir, exist_ok=True)

    orders = [args.start_order + i for i in range(args.count)]
    if args.replace:
        remove_existing_game_files(work_dir, date_str, orders)

    print(f"[DIR] {work_dir}")
    print(f"[DIR] 원본: {VIDEO_FOLDER}")
    print(f"[INFO] 매치 후보 {len(matches)}개")
    print()

    vm = VideoManager()
    for i, orig in enumerate(originals):
        order = orders[i]
        rec_start, rec_end = VideoManager.get_recording_times_from_file(orig)
        game_id = match_game_id(rec_end, matches)
        print("=" * 60)
        print(f"[{i+1}/{args.count}] 게임 {order:02d}")
        print(f"  원본: {os.path.basename(orig)}")
        print(f"  종료: {datetime.datetime.fromtimestamp(rec_end)}")
        if not game_id:
            print("[ERROR] 매치 매칭 실패 (10분 이내 종료 시각 없음)")
            return 1
        print(f"  gameId={game_id}")
        vm.process_ranked_match(
            rec_start,
            SOLO_DUO_QUEUE_ID,
            recording_end_time_override=rec_end,
            video_path_override=orig,
            game_id_override=game_id,
            output_dir_override=work_dir,
            game_num_override=order,
            skip_match_wait=True,
            open_video_override=False,
        )
        print()

    print("[DONE] 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
