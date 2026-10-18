"""
솔랭 폴더 목록(게임 ID·순서) + 원본 최근 N개를 1:1 매칭해 일괄 재편집.

예:
  python batch_reprocess_ranked.py --list-dir "C:\\Users\\seok\\Videos\\솔랭\\260604" --work-dir "...\\임시" --count 6
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from env import VIDEO_FOLDER  # noqa: E402
from modules.video_manager import SOLO_DUO_QUEUE_ID, VideoManager  # noqa: E402

GAME_ID_RE = re.compile(r"\b(\d{10})\b")


def parse_games_from_list_dir(list_dir: str) -> list[tuple[int, str]]:
    """폴더 내 mkv 파일명에서 (순번, gameId) 추출."""
    entries: list[tuple[int, str]] = []
    for path in glob.glob(os.path.join(list_dir, "*.mkv")):
        name = os.path.basename(path)
        m_order = re.match(r"^(\d{6})\s+(\d{2})\s", name)
        if not m_order:
            continue
        order = int(m_order.group(2))
        m_gid = GAME_ID_RE.search(name)
        if not m_gid:
            continue
        entries.append((order, m_gid.group(1)))
    entries.sort(key=lambda x: x[0])
    return entries


def pick_originals(count: int) -> list[str]:
    paths: list[str] = []
    for ext in ("*.mkv", "*.mp4"):
        paths.extend(glob.glob(os.path.join(VIDEO_FOLDER, ext)))
    paths.sort(key=os.path.getmtime)
    return paths[-count:]


def pick_original_for_order(order: int, day_count: int) -> str | None:
    """당일 원본 N개 중 order번째 (1=가장 이른 게임)."""
    originals = pick_originals(day_count)
    if order < 1 or order > len(originals):
        return None
    return originals[order - 1]


def remove_existing_game_files(work_dir: str, date_prefix: str, orders: list[int]) -> None:
    for path in glob.glob(os.path.join(work_dir, f"{date_prefix} *.mkv")):
        name = os.path.basename(path)
        m = re.match(r"^\d{6}\s+(\d{2})\s", name)
        if m and int(m.group(1)) in orders:
            os.remove(path)
            print(f"[DEL] {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="솔랭 영상 일괄 재편집")
    parser.add_argument(
        "--list-dir",
        default=r"C:\Users\seok\Videos\솔랭\260604",
        help="게임 ID·순서가 적힌 mkv 목록 폴더",
    )
    parser.add_argument(
        "--work-dir",
        default=r"C:\Users\seok\Videos\솔랭\260604\임시",
        help="결과물 저장 폴더",
    )
    parser.add_argument("--count", type=int, default=6, help="처리할 판 수 (전체 일괄 시)")
    parser.add_argument(
        "--orders",
        help="특정 번호만 처리 (예: 2,3 또는 02,03)",
    )
    parser.add_argument(
        "--day-count",
        type=int,
        default=6,
        help="당일 원본 개수 (--orders 사용 시 순번 매칭용)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="작업 폴더의 동일 번호 기존 파일 삭제 후 저장",
    )
    args = parser.parse_args()

    all_games = parse_games_from_list_dir(args.list_dir)
    if not all_games:
        print("[ERROR] 목록 폴더에서 게임을 찾지 못했습니다.")
        return 1

    if args.orders:
        wanted = {int(x.strip()) for x in args.orders.split(",") if x.strip()}
        games = [(o, gid) for o, gid in all_games if o in wanted]
        if len(games) != len(wanted):
            found = {o for o, _ in games}
            missing = wanted - found
            print(f"[ERROR] 목록에서 번호를 찾지 못함: {sorted(missing)}")
            return 1
        games.sort(key=lambda x: x[0])
        pairs: list[tuple[tuple[int, str], str]] = []
        for order, game_id in games:
            orig = pick_original_for_order(order, args.day_count)
            if not orig:
                print(f"[ERROR] 원본 {order}번 매칭 실패 (day-count={args.day_count})")
                return 1
            pairs.append(((order, game_id), orig))
    else:
        if len(all_games) < args.count:
            print(f"[ERROR] 목록 폴더에서 게임 {args.count}개를 찾지 못했습니다. (발견: {len(all_games)})")
            return 1
        games = all_games[: args.count]
        originals = pick_originals(args.count)
        if len(originals) < args.count:
            print(f"[ERROR] 원본 폴더에서 파일 {args.count}개를 찾지 못했습니다. (발견: {len(originals)})")
            return 1
        pairs = list(zip(games, originals))

    os.makedirs(args.work_dir, exist_ok=True)

    if args.replace and pairs:
        date_prefix = os.path.basename(args.list_dir.rstrip("\\/"))
        if re.match(r"^\d{6}$", date_prefix):
            remove_existing_game_files(
                args.work_dir,
                date_prefix,
                [order for (order, _), _ in pairs],
            )

    print(f"[DIR] 작업 폴더: {args.work_dir}")
    print(f"[DIR] 목록: {args.list_dir}")
    print(f"[DIR] 원본: {VIDEO_FOLDER}")
    print()

    vm = VideoManager()
    total = len(pairs)
    for i, ((order, game_id), orig_path) in enumerate(pairs, start=1):
        start_time, end_time = VideoManager.get_recording_times_from_file(orig_path)
        print("=" * 60)
        print(f"[{i}/{total}] 게임 {order:02d} | gameId={game_id}")
        print(f"  원본: {os.path.basename(orig_path)}")
        print(f"  녹화 종료(추정): {end_time}")
        print()

        vm.process_ranked_match(
            start_time,
            SOLO_DUO_QUEUE_ID,
            recording_end_time_override=end_time,
            video_path_override=orig_path,
            game_id_override=game_id,
            output_dir_override=args.work_dir,
            game_num_override=order,
            skip_match_wait=True,
            open_video_override=False,
        )
        print()

    print("[DONE] 일괄 처리 요청 완료. 결과는 작업 폴더를 확인하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
