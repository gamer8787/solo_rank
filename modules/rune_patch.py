"""이미 편집·업로드된 영상에 룬 오버레이만 뒤늦게 끼워 넣는다.

원본 재편집(modules.loading_intro.build_video_with_overlays)과 달리 이쪽은
로딩 정지프레임이 이미 들어있는 완성본을 입력으로 받는다. 그래서 하는 일은
"특정 구간에 PNG 한 장 올리기" 뿐이다.

전체 재인코딩은 35분짜리 1080p60 에 너무 비싸므로 앞부분만 다시 인코딩하고
나머지는 copy 로 이어붙인다.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile

from modules.loading_intro import (
    RUNE_OVERLAY_SEC,
    _run_ffmpeg,
    concat_clip_list,
    find_next_keyframe,
    probe_video,
)

# 로딩 정지프레임이 끝난 뒤에도 딥롤 오버레이가 1초 가까이 더 남아있어 겹친다.
# 그만큼 뒤로 밀어서 룬 패널이 티어 텍스트와 겹치지 않게 한다.
RUNE_START_MARGIN_SEC = 1.3

_FREEZE_END_RE = re.compile(r"freezedetect.*freeze_end:\s*([\d.]+)")
_FREEZE_START_RE = re.compile(r"freezedetect.*freeze_start:\s*([\d.]+)")


def detect_intro_end(video_path: str, search_sec: float = 20.0) -> float | None:
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

    # 0초부터 시작하는 첫 freeze 구간만 로딩 인트로로 본다.
    starts = [float(m) for m in _FREEZE_START_RE.findall(log)]
    ends = [float(m) for m in _FREEZE_END_RE.findall(log)]
    if not starts or not ends:
        return None
    if starts[0] > 0.5:
        return None
    return ends[0]


def add_rune_overlay(
    video_path: str,
    output_path: str,
    rune_png: str,
    *,
    intro_end_sec: float | None = None,
    rune_sec: float = RUNE_OVERLAY_SEC,
    margin_sec: float = RUNE_START_MARGIN_SEC,
) -> dict:
    """완성본 영상의 게임 시작 직후 구간에 룬 PNG 를 올린다."""
    if not os.path.exists(rune_png):
        raise FileNotFoundError(f"룬 PNG 없음: {rune_png}")

    meta = probe_video(video_path)
    width, height, fps = meta["width"], meta["height"], meta["fps"]
    duration = meta["duration"]

    if intro_end_sec is None:
        intro_end_sec = detect_intro_end(video_path)
    if intro_end_sec is None:
        raise RuntimeError("로딩 정지프레임 구간을 찾지 못했습니다 (freezedetect 실패)")

    rune_start = intro_end_sec + margin_sec
    rune_end = rune_start + rune_sec
    if duration and rune_end > duration - 1.0:
        raise RuntimeError(f"영상이 너무 짧습니다 (길이 {duration:.1f}s, 룬 종료 {rune_end:.1f}s)")

    # 이음새는 룬이 끝난 뒤 첫 키프레임. copy 컷이 밀리지 않게 dts 기준으로 자른다.
    kf = find_next_keyframe(video_path, rune_end)
    if kf is None:
        raise RuntimeError(f"{rune_end:.2f}s 이후 키프레임을 찾지 못했습니다")
    cut_pts, cut_dts = kf
    body_ss = max(0.0, cut_dts - 0.001)

    print(f"[룬합성] 인트로 종료 {intro_end_sec:.3f}s → 룬 {rune_start:.2f}~{rune_end:.2f}s")
    print(f"[룬합성] 이음새 키프레임 pts={cut_pts:.3f}s dts={cut_dts:.3f}s")

    work_dir = tempfile.mkdtemp(prefix="rune_patch_")
    head = os.path.join(work_dir, "head.mkv")
    body = os.path.join(work_dir, "body.mkv")
    try:
        # 헤드: 0 ~ 이음새. 비디오만 재인코딩, 오디오는 그대로 copy.
        _run_ffmpeg([
            "ffmpeg", "-y",
            "-i", video_path,
            "-loop", "1", "-framerate", f"{fps:.6f}", "-i", rune_png,
            "-filter_complex",
            f"[1:v]format=rgba,scale={width}:{height}[ro];"
            f"[0:v][ro]overlay=0:0:format=auto:"
            f"enable='between(t,{rune_start:.3f},{rune_end:.3f})',format=yuv420p[v]",
            "-map", "[v]", "-map", "0:a?",
            "-t", f"{cut_pts:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-r", f"{fps:.6f}", "-fps_mode", "cfr",
            head,
        ])

        # 본편: 이음새 ~ 끝. 전부 copy.
        # -ss 는 반드시 -i 뒤(출력 시크). 앞에 두면 입력 시크가 되어 이전 키프레임까지
        # 되감겨 본편이 앞쪽부터 중복된다.
        _run_ffmpeg([
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", f"{body_ss:.3f}",
            "-map", "0",
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            body,
        ])

        print("[룬합성] 이어붙이는 중 (copy)...")
        concat_clip_list([head, body], output_path, width, height, fps)
    finally:
        for name in os.listdir(work_dir):
            try:
                os.remove(os.path.join(work_dir, name))
            except OSError:
                pass
        try:
            os.rmdir(work_dir)
        except OSError:
            pass

    return {
        "intro_end": intro_end_sec,
        "rune_start": rune_start,
        "rune_end": rune_end,
        "cut": cut_pts,
    }
