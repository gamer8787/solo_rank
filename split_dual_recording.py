"""한 원본 파일에 연속 녹화된 솔랭 2판을 각각 분리 저장."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.video_manager import SOLO_DUO_QUEUE_ID, VideoManager

VIDEO_PATH = r"C:\Users\seok\Videos\원본\2026-06-10 15-01-49.mkv"
OUTPUT_DIR = r"C:\Users\seok\Videos\솔랭\260610"

GAMES = [
    (1, "8252946570"),  # Jax — 녹화가 게임 시작 후
    (2, "8252979069"),  # Jayce — 로딩 포함
]


def main() -> int:
    if not os.path.exists(VIDEO_PATH):
        print(f"[ERROR] 원본 없음: {VIDEO_PATH}")
        return 1

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    rec_start, rec_end = VideoManager.get_recording_times_from_file(VIDEO_PATH)
    print(f"[FILE] {os.path.basename(VIDEO_PATH)}")
    print(f"[REC] start={rec_start} end={rec_end}")

    vm = VideoManager()
    for game_num, game_id in GAMES:
        print("=" * 60)
        print(f"[GAME {game_num:02d}] gameId={game_id}")
        vm.process_ranked_match(
            rec_start,
            SOLO_DUO_QUEUE_ID,
            recording_end_time_override=rec_end,
            video_path_override=VIDEO_PATH,
            game_id_override=game_id,
            output_dir_override=OUTPUT_DIR,
            game_num_override=game_num,
            skip_match_wait=True,
            open_video_override=False,
        )
        print()

    print("[DONE] 260610 폴더 확인")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
