"""로딩창(딥롤 오버레이) + 게임 시작 직후 룬 오버레이를 영상에 합성.

이음새를 1곳으로 줄이는 구조:
  [A] 로딩 정지프레임 4초 + 게임 시작부터 키프레임까지  (재인코딩, 오디오는 연속 copy)
  [B] 그 키프레임부터 게임 종료까지                      (전부 copy)
  A + B 를 copy concat → 겹치는 구간·중복 효과음 없음.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

try:
    import cv2
except ImportError:
    cv2 = None

LOADING_OVERLAY_SEC = 4.0
RUNE_OVERLAY_SEC = 5.0


def overlay_frame_count(fps: float, duration: float = LOADING_OVERLAY_SEC) -> int:
    """오버레이 길이를 프레임 단위로 고정 (예: 60fps → 240프레임 = 4.0s)."""
    return max(1, int(round(fps * duration)))


def overlay_duration_sec(fps: float, duration: float = LOADING_OVERLAY_SEC) -> float:
    return overlay_frame_count(fps, duration) / fps


BLACK_FRAME_MEAN_THRESHOLD = 20.0
LOADING_FRAME_MEAN_THRESHOLD = 28.0
LOADING_FRAME_STD_THRESHOLD = 22.0


def _run_ffmpeg(cmd: list[str]) -> None:
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        tail = (result.stderr or "")[-800:]
        raise RuntimeError(f"ffmpeg 실패: {tail}")


def count_audio_streams(path: str) -> int:
    import json

    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "json",
        path,
    ]
    raw = subprocess.check_output(cmd, text=True, encoding="utf-8")
    streams = json.loads(raw).get("streams") or []
    return len(streams)


def probe_video(path: str) -> dict:
    import json

    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,duration,start_time",
        "-of", "json",
        path,
    ]
    raw = subprocess.check_output(cmd, text=True, encoding="utf-8")
    stream = json.loads(raw)["streams"][0]
    num, den = stream["r_frame_rate"].split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    try:
        start_time = float(stream.get("start_time") or 0.0)
    except (TypeError, ValueError):
        start_time = 0.0
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": fps or 30.0,
        "duration": float(stream.get("duration") or 0.0),
        "start_time": start_time,
        "audio_streams": count_audio_streams(path),
    }


def find_next_keyframe(video_path: str, from_sec: float, search_sec: float = 20.0) -> tuple[float, float] | None:
    """
    from_sec 이후(포함) 첫 비디오 키프레임의 (pts, dts).

    copy 로 자를 때 ffmpeg 은 dts 기준으로 앞 패킷을 버린다. B프레임 때문에
    키프레임의 dts 는 pts 보다 앞서므로, dts 를 알아야 그 키프레임을 살릴 수 있다.
    """
    start = max(0.0, from_sec - 2.0)
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "packet=pts_time,dts_time,flags",
        "-of", "csv=p=0",
        "-read_intervals", f"{start:.3f}%+{search_sec:.3f}",
        video_path,
    ]
    try:
        raw = subprocess.check_output(cmd, text=True, encoding="utf-8")
    except subprocess.CalledProcessError:
        return None

    keys: list[tuple[float, float]] = []
    for line in raw.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 3 or "K" not in parts[2]:
            continue
        try:
            pts = float(parts[0])
        except ValueError:
            continue
        try:
            dts = float(parts[1])
        except ValueError:
            dts = pts
        keys.append((pts, min(dts, pts)))

    for pts, dts in sorted(keys):
        if pts >= from_sec - 1e-3:
            return pts, dts
    return None


def _frame_stats(frame) -> tuple[float, float]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(gray.mean()), float(gray.std())


def is_black_frame(mean: float) -> bool:
    return mean < BLACK_FRAME_MEAN_THRESHOLD


def is_loading_frame(mean: float, std: float) -> bool:
    return mean >= LOADING_FRAME_MEAN_THRESHOLD and std >= LOADING_FRAME_STD_THRESHOLD


def read_frame_at(video_path: str, time_sec: float):
    if cv2 is None:
        return None
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, time_sec) * 1000.0)
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def classify_start_frame(video_path: str) -> str:
    """첫 장면 분류: 'loading' | 'black' | 'unknown'."""
    frame = read_frame_at(video_path, 0.0)
    if frame is None:
        return "unknown"
    mean, std = _frame_stats(frame)
    if is_loading_frame(mean, std):
        return "loading"
    if is_black_frame(mean):
        return "black"
    return "unknown"


def find_loading_frame_time(
    video_path: str,
    max_search_sec: float = 20.0,
    step_sec: float = 0.25,
    start_sec: float = 0.0,
) -> float | None:
    """start_sec 부터 앞으로 훑어 로딩창 프레임 시각을 찾는다."""
    if cv2 is None:
        return None
    t = max(0.0, start_sec)
    end = (start_sec + max_search_sec) if start_sec > 0 else max_search_sec
    while t <= end:
        frame = read_frame_at(video_path, t)
        if frame is None:
            break
        mean, std = _frame_stats(frame)
        if is_loading_frame(mean, std):
            return t
        t += step_sec
    return None


def find_loading_frame_before_game(
    video_path: str,
    game_start_in_video: float,
    search_back_sec: float = 90.0,
    step_sec: float = 0.5,
) -> float | None:
    """게임 시작 직전 구간을 뒤에서부터 훑어 로딩창 프레임을 찾는다."""
    if cv2 is None:
        return None
    end = max(0.0, game_start_in_video)
    start = max(0.0, end - search_back_sec)
    t = end
    while t >= start:
        frame = read_frame_at(video_path, t)
        if frame is None:
            break
        mean, std = _frame_stats(frame)
        if is_loading_frame(mean, std):
            best = t
            earlier = max(start, t - 3.0)
            te = t
            while te >= earlier:
                fr = read_frame_at(video_path, te)
                if fr is None:
                    break
                m, s = _frame_stats(fr)
                if is_loading_frame(m, s):
                    best = te
                else:
                    break
                te -= step_sec
            return best
        t -= step_sec
    return None


def extract_frame_png(video_path: str, time_sec: float, output_png: str) -> None:
    _run_ffmpeg([
        "ffmpeg", "-y",
        "-ss", f"{time_sec:.3f}",
        "-i", video_path,
        "-frames:v", "1",
        output_png,
    ])


def concat_clip_list(paths: list[str], output_path: str, width: int, height: int, fps: float) -> None:
    """여러 클립을 한 번에 concat. 우선 -c copy, 실패 시만 재인코딩."""
    if not paths:
        raise ValueError("concat 할 클립이 없습니다.")
    if len(paths) == 1:
        if os.path.abspath(paths[0]) != os.path.abspath(output_path):
            import shutil
            shutil.copy2(paths[0], output_path)
        return

    n_audio = 0
    for p in paths:
        n_audio = max(n_audio, count_audio_streams(p))

    list_path = output_path + ".concat.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in paths:
            f.write(f"file '{p.replace(chr(92), '/')}'\n")
    try:
        _run_ffmpeg([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-map", "0",
            "-c", "copy",
            output_path,
        ])
    except RuntimeError:
        n = len(paths)
        print(f"[합성] copy 합치기 실패 → 재인코딩 ({n}클립, 오디오 {n_audio}트랙)")
        fc_parts = []
        v_labels = []
        for i in range(n):
            fc_parts.append(
                f"[{i}:v]scale={width}:{height},fps={fps},setpts=PTS-STARTPTS[v{i}];"
            )
            v_labels.append(f"[v{i}]")
        fc_parts.append(f"{''.join(v_labels)}concat=n={n}:v=1:a=0[v]")

        audio_out_labels = []
        for ai in range(n_audio):
            a_labels = []
            for i in range(n):
                fc_parts.append(
                    f"[{i}:a:{ai}]aformat=sample_rates=48000:channel_layouts=stereo,"
                    f"asetpts=PTS-STARTPTS[a{i}_{ai}];"
                )
                a_labels.append(f"[a{i}_{ai}]")
            fc_parts.append(f"{''.join(a_labels)}concat=n={n}:v=0:a=1[aout_{ai}]")
            audio_out_labels.append(f"[aout_{ai}]")

        cmd = ["ffmpeg", "-y"]
        for p in paths:
            cmd.extend(["-i", p])
        cmd += ["-filter_complex", "".join(fc_parts), "-map", "[v]"]
        for label in audio_out_labels:
            cmd.extend(["-map", label])
        cmd += [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            output_path,
        ]
        _run_ffmpeg(cmd)
    finally:
        try:
            os.remove(list_path)
        except OSError:
            pass


def concat_clips(intro_path: str, body_path: str, output_path: str, width: int, height: int, fps: float) -> None:
    concat_clip_list([intro_path, body_path], output_path, width, height, fps)


def _build_head_video(
    *,
    video_path: str,
    loading_frame_png: str,
    loading_overlay_png: str,
    rune_overlay_png: str | None,
    game_pos: float,
    game_part_dur: float,
    intro_frames: int,
    total_frames: int,
    rune_sec: float,
    width: int,
    height: int,
    fps: float,
    output_path: str,
) -> None:
    """로딩 정지프레임 + 게임 구간(룬 오버레이)을 한 번에 인코딩 (비디오만)."""
    intro_dur = intro_frames / fps
    src_dur = game_part_dur + 0.5  # 프레임 수는 -frames:v 로 확정

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", f"{fps:.6f}", "-t", f"{intro_dur:.3f}", "-i", loading_frame_png,
        "-loop", "1", "-framerate", f"{fps:.6f}", "-t", f"{intro_dur:.3f}", "-i", loading_overlay_png,
        "-ss", f"{game_pos:.3f}", "-t", f"{src_dur:.3f}", "-i", video_path,
    ]

    fc = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:.6f},format=rgba[bg];",
        f"[1:v]format=rgba,scale={width}:{height}[lo];",
        "[bg][lo]overlay=0:0:format=auto,setpts=PTS-STARTPTS,format=yuv420p[introv];",
    ]

    if rune_overlay_png:
        cmd += ["-loop", "1", "-framerate", f"{fps:.6f}", "-t", f"{src_dur:.3f}", "-i", rune_overlay_png]
        fc += [
            f"[2:v]fps={fps:.6f},scale={width}:{height},setsar=1[gv];",
            f"[3:v]format=rgba,scale={width}:{height}[ro];",
            f"[gv][ro]overlay=0:0:format=auto:enable='lt(t,{rune_sec:.3f})',"
            "setpts=PTS-STARTPTS,format=yuv420p[gamev];",
        ]
    else:
        fc += [
            f"[2:v]fps={fps:.6f},scale={width}:{height},setsar=1,"
            "setpts=PTS-STARTPTS,format=yuv420p[gamev];",
        ]

    fc.append("[introv][gamev]concat=n=2:v=1:a=0[vout]")

    cmd += [
        "-filter_complex", "".join(fc),
        "-map", "[vout]",
        "-an",
        "-frames:v", str(total_frames),
        "-r", f"{fps:.6f}",
        "-fps_mode", "cfr",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        output_path,
    ]
    _run_ffmpeg(cmd)


def _build_head_audio(
    *,
    video_path: str,
    n_audio: int,
    audio_start: float,
    audio_dur: float,
    silence_head: float,
    output_path: str,
) -> None:
    """헤드 구간 오디오. 원본 [audio_start, +audio_dur] 를 통째로 copy (연속 → 중복 없음)."""
    if silence_head <= 0.001:
        # -ss 는 반드시 -i 뒤(출력 시크). 앞에 두면 패킷이 앞으로 밀려 소리가 겹친다.
        _run_ffmpeg([
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", f"{audio_start:.3f}",
            "-t", f"{audio_dur:.3f}",
            "-vn",
            "-map", "0:a",
            "-c:a", "copy",
            output_path,
        ])
        return

    # 녹화가 게임 시작 직전에 시작된 드문 경우: 앞부분만 무음으로 채움
    body_dur = max(0.05, audio_dur - silence_head)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-t", f"{silence_head:.3f}",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-ss", f"{audio_start:.3f}", "-t", f"{body_dur:.3f}", "-i", video_path,
    ]
    fc = []
    maps = []
    for i in range(n_audio):
        fc.append(
            "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[s%d];" % i
        )
        fc.append(
            f"[1:a:{i}]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[b{i}];"
        )
        fc.append(f"[s{i}][b{i}]concat=n=2:v=0:a=1[a{i}];")
        maps += ["-map", f"[a{i}]"]

    cmd += ["-filter_complex", "".join(fc).rstrip(";"), *maps, "-c:a", "aac", "-b:a", "192k", output_path]
    _run_ffmpeg(cmd)


def build_video_with_overlays(
    video_path: str,
    output_path: str,
    *,
    loading_overlay_png: str,
    rune_overlay_png: str | None,
    game_pos_sec: float,
    body_end_sec: float,
    loading_sec: float = LOADING_OVERLAY_SEC,
    rune_sec: float = RUNE_OVERLAY_SEC,
) -> None:
    """
    game_pos_sec  : 원본에서 게임이 시작되는 위치 (game_start - recording_start)
    body_end_sec  : 원본에서 게임이 끝나는 위치 (game_end - recording_start)

    로딩 정지프레임 4초(딥롤 아이디·티어) → 게임 시작부터 룬 5초 → 나머지 copy.
    """
    if not os.path.exists(loading_overlay_png):
        raise FileNotFoundError(f"로딩 오버레이 PNG 없음: {loading_overlay_png}")

    meta = probe_video(video_path)
    width, height, fps = meta["width"], meta["height"], meta["fps"]
    n_audio = meta.get("audio_streams") or 0
    game_pos = max(0.0, float(game_pos_sec))
    body_end = float(body_end_sec)
    if body_end - game_pos <= rune_sec + 1.0:
        raise RuntimeError("게임 구간이 너무 짧아 오버레이를 넣을 수 없습니다.")

    intro_frames = overlay_frame_count(fps, loading_sec)

    # 이음새를 키프레임에 정확히 맞춘다 → copy 컷이 밀리거나 겹치는 현상 방지
    cut_target = game_pos + rune_sec
    kf = find_next_keyframe(video_path, cut_target)
    if kf is None or kf[0] >= body_end - 1.0:
        cut_t = cut_target
        body_ss = cut_target
        print(f"[합성] 키프레임 탐색 실패 → {cut_t:.2f}s 로 컷")
    else:
        cut_t, kf_dts = kf
        # dts 보다 살짝 앞에서 잘라야 이 키프레임이 살아남는다 (안 그러면 다음 GOP까지 밀림)
        body_ss = max(0.0, kf_dts - 0.001)
        print(f"[합성] 이음새 키프레임 pts={cut_t:.3f}s dts={kf_dts:.3f}s (룬 종료 {cut_target:.2f}s 직후)")

    # 프레임 인덱스로 계산해 head 끝과 body 시작을 정확히 맞춘다
    first_game_frame = int(-(-game_pos * fps // 1))  # ceil
    cut_frame = int(round(cut_t * fps))
    game_frames = max(1, cut_frame - first_game_frame)
    game_part_dur = game_frames / fps
    total_frames = intro_frames + game_frames
    head_dur = total_frames / fps

    if n_audio:
        print(f"[합성] 원본 오디오 트랙 {n_audio}개 유지")

    work_dir = tempfile.mkdtemp(prefix="overlay_build_")
    try:
        loading_t = find_loading_frame_before_game(video_path, game_pos)
        if loading_t is None:
            loading_t = find_loading_frame_time(video_path, max_search_sec=max(20.0, game_pos))
        if loading_t is None:
            loading_t = max(0.0, game_pos - 1.0)
            print(f"[로딩창] 로딩 프레임 미감지 → {loading_t:.2f}s 프레임 사용")
        else:
            print(f"[로딩창] 로딩 프레임 {loading_t:.2f}s + 딥롤 오버레이 {intro_frames / fps:.2f}s")

        frame_png = os.path.join(work_dir, "loading_frame.png")
        head_v = os.path.join(work_dir, "head_v.mkv")
        head_a = os.path.join(work_dir, "head_a.mkv")
        head = os.path.join(work_dir, "head.mkv")
        body = os.path.join(work_dir, "body.mkv")

        extract_frame_png(video_path, loading_t, frame_png)

        print(f"[합성] 1/3 로딩 {loading_sec:.0f}s + 룬 {rune_sec:.0f}s 인코딩 ({total_frames}프레임)")
        _build_head_video(
            video_path=video_path,
            loading_frame_png=frame_png,
            loading_overlay_png=loading_overlay_png,
            rune_overlay_png=rune_overlay_png,
            game_pos=game_pos,
            game_part_dur=game_part_dur,
            intro_frames=intro_frames,
            total_frames=total_frames,
            rune_sec=rune_sec,
            width=width,
            height=height,
            fps=fps,
            output_path=head_v,
        )

        if n_audio:
            # 본편 오디오가 시작되는 지점(body_ss)에서 끝나도록 뒤에서 역산 → 소리 겹침·중복 없음
            audio_start = body_ss - head_dur
            silence_head = max(0.0, -audio_start)
            audio_start = max(0.0, audio_start)
            _build_head_audio(
                video_path=video_path,
                n_audio=n_audio,
                audio_start=audio_start,
                audio_dur=head_dur,
                silence_head=silence_head,
                output_path=head_a,
            )
            _run_ffmpeg([
                "ffmpeg", "-y",
                "-i", head_v,
                "-i", head_a,
                "-map", "0:v",
                "-map", "1:a",
                "-c", "copy",
                "-shortest",
                head,
            ])
        else:
            head = head_v

        print(f"[합성] 2/3 본편 copy ({cut_t:.2f}s → {body_end:.0f}s)")
        _run_ffmpeg([
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", f"{body_ss:.3f}",
            "-t", f"{max(0.1, body_end - body_ss):.3f}",
            "-map", "0",
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            body,
        ])
        body_meta = probe_video(body)
        gap_ms = float(body_meta.get("start_time") or 0.0) * 1000.0
        if abs(gap_ms) > 40.0:
            print(f"[합성] ⚠️ 본편 영상이 {gap_ms:.0f}ms 늦게 시작 (이음새 버벅임 가능)")

        print("[합성] 3/3 이어붙이는 중 (copy)...")
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
