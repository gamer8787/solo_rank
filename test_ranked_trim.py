"""
main.py 과 동일한 VideoManager 후처리(앞쪽 3초 로딩 오버레이 + 게임 종료까지) 테스트.

실행 방법 (프로젝트 루트):
  python test_ranked_trim.py              # 솔랭(420) 폴더로 저장 테스트
  python test_ranked_trim.py --flex        # 자유랭(440) 폴더로 저장 테스트
  python test_ranked_trim.py --file "C:\\path\\to\\video.mkv"

원본 폴더(env.VIDEO_FOLDER)에서 수정 시각(mtime)이 가장 최근인 .mkv / .mp4 를 고릅니다.
녹화 시작·종료 시각은 main.py 와 같이 mtime 과 영상 길이로 추정합니다 (복사본 ctime 무시).

주의:
  매치 매칭이 안 되거나 트림이 실패하면 영상은 etc 폴더로 옮길 수 있습니다.
  테스트 전 백업을 권장합니다.
"""

from __future__ import annotations

import argparse
import datetime
import glob
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from env import VIDEO_FOLDER  # noqa: E402
from modules.video_manager import VideoManager  # noqa: E402
from modules.video_manager import FLEX_RANK_QUEUE_ID, SOLO_DUO_QUEUE_ID  # noqa: E402


def pick_latest_original() -> str | None:
    paths: list[str] = []
    for ext in ('*.mkv', '*.mp4'):
        paths.extend(glob.glob(os.path.join(VIDEO_FOLDER, ext)))
    if not paths:
        return None
    return max(paths, key=os.path.getmtime)


def _fmt_ts(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')


def main() -> int:
    parser = argparse.ArgumentParser(description='랭크 영상 후처리(솔랭/자유랭 폴더) 테스트')
    parser.add_argument(
        '--flex',
        action='store_true',
        help='저장 위치를 자유랭(FLEX_RANK_VIDEO_FOLDER) 으로 (트림 규칙은 동일)',
    )
    parser.add_argument(
        '--file',
        help='처리할 영상 경로 (미지정 시 원본 폴더에서 mtime 최신 파일)',
    )
    args = parser.parse_args()
    queue_id = FLEX_RANK_QUEUE_ID if args.flex else SOLO_DUO_QUEUE_ID
    folder_hint = '자유랭' if args.flex else '솔랭'

    path = args.file or pick_latest_original()
    if not path or not os.path.exists(path):
        print(f'❌ 영상 파일을 찾을 수 없습니다: {path or VIDEO_FOLDER}')
        return 1

    start_time, end_time = VideoManager.get_recording_times_from_file(path)
    duration = end_time - start_time

    print(f'📹 대상 파일: {path}')
    print(f'   저장 모드 테스트: {folder_hint} (queue_id={queue_id})')
    print(f'   녹화 시작(추정): {_fmt_ts(start_time)}  ← mtime - {duration:.0f}s')
    print(f'   녹화 종료(추정): {_fmt_ts(end_time)}  ← mtime')

    vm = VideoManager()
    vm.process_ranked_match(
        start_time,
        queue_id,
        recording_end_time_override=end_time,
        video_path_override=path,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
