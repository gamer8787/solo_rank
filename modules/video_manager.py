import os
import time
import glob
import json
import datetime
import shutil
import subprocess
import requests
import urllib3

# env.py 및 api.py 위치 찾기
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from env import (
    VIDEO_FOLDER,
    NEW_VIDEO_FOLDER,
    FLEX_RANK_VIDEO_FOLDER,
    ETC_VIDEO_FOLDER,
    API_KEY,
    OPEN_VIDEO,
)
from api import (
    get_tier_detail_by_puuid,
    convert_tier_detail,
    get_summoner_name_by_puuid,
    get_match_by_gameId,
)
from deeplol import build_deeplol_match_url, save_loading_overlay
from modules.loading_intro import (
    LOADING_OVERLAY_SEC,
    RUNE_OVERLAY_SEC,
    build_video_with_overlays,
)
from modules.rune_overlay import save_rune_overlay_png

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 솔로/듀오(420), 자유랭/플렉스(440) — 트림 후 각각 다른 루트 폴더에 저장
SOLO_DUO_QUEUE_ID = 420
FLEX_RANK_QUEUE_ID = 440
RANKED_SAVE_QUEUE_IDS = frozenset({SOLO_DUO_QUEUE_ID, FLEX_RANK_QUEUE_ID})

# 라이엇 gameStart 기준 로딩 앞쪽만 유지
TRIM_SECONDS_BEFORE_GAME_START = LOADING_OVERLAY_SEC
# 녹화 시작과 게임 시작 시각 차이 ±N초 이내면 앞 트림 생략 (검은 화면이 짧다고 간주)
TRIM_SKIP_IF_START_WITHIN_GAME_SEC = LOADING_OVERLAY_SEC

# 매치 검색 시 녹화 구간 앞뒤로 넉넉히 둘 여유 (초)
MATCH_SEARCH_MARGIN_SEC = 600
# 게임 직후 매치가 API 에 올라올 때까지 재시도 (고정 대기 대신)
MATCH_RETRY_INTERVAL_SEC = 3
MATCH_WAIT_TIMEOUT_SEC = 90


class VideoManager:
    def __init__(self):
        self.api_key = API_KEY
        self.champ_map_eng_to_kr = self._load_champion_eng_to_kr()

    def _load_champion_eng_to_kr(self):
        mapping = {}
        try:
            ver_url = "https://ddragon.leagueoflegends.com/api/versions.json"
            version = requests.get(ver_url).json()[0]
            url = f"http://ddragon.leagueoflegends.com/cdn/{version}/data/ko_KR/champion.json"
            data = requests.get(url).json()['data']
            for champ_data in data.values():
                mapping[champ_data['id']] = champ_data['name']
            return mapping
        except:
            return {}

    def play_sound(self, file_name):
        import pygame
        if not pygame.mixer.get_init(): pygame.mixer.init()
        try:
            pygame.mixer.music.load(file_name);
            pygame.mixer.music.play()
        except:
            pass

    def get_most_recent_video(self):
        list_of_files = []
        for ext in ('*.mkv', '*.mp4'):
            list_of_files.extend(glob.glob(os.path.join(VIDEO_FOLDER, ext)))
        if not list_of_files:
            return None
        return max(list_of_files, key=os.path.getmtime)

    @staticmethod
    def get_video_duration_sec(video_path: str) -> float:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            video_path,
        ]
        raw = subprocess.check_output(cmd, text=True, encoding="utf-8")
        duration = json.loads(raw).get("format", {}).get("duration")
        if duration is None:
            raise RuntimeError(f"영상 길이를 읽을 수 없습니다: {video_path}")
        return float(duration)

    @staticmethod
    def get_recording_times_from_file(video_path: str) -> tuple[float, float]:
        """
        main.py 와 동일한 기준으로 녹화 시작·종료 시각 추정.
        - 종료: 파일 수정 시각(mtime) — OBS 녹화 종료 시점
        - 시작: 종료 - 영상 길이 — InProgress 시 녹화 시작에 대응
        복사본 ctime 이 아닌 mtime·duration 을 사용한다.
        """
        end_time = os.path.getmtime(video_path)
        duration = VideoManager.get_video_duration_sec(video_path)
        start_time = end_time - duration
        return start_time, end_time

    def trim_video(self, input_file, output_file, start_time, duration=None):
        """
        [수정] ffmpeg로 시작 시간뿐만 아니라 종료 시간(지속 시간)까지 제어
        -ss: 시작 지점
        -t: 지속 시간 (이 시간이 지나면 자름)
        """
        command = ['ffmpeg', '-y', '-i', input_file, '-ss', str(start_time)]
        if duration:
            command += ['-t', str(duration)]

        command += ['-map', '0', '-c', 'copy', '-avoid_negative_ts', 'make_zero', '-y', output_file]

        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        except Exception as e:
            print(f"❌ 영상 자르기 실패: {e}")

    def get_next_game_number(self, date_str, output_root_folder):
        date_folder = os.path.join(output_root_folder, date_str)
        if not os.path.exists(date_folder):
            return 1
        files = glob.glob(os.path.join(date_folder, f"{date_str} *.mkv"))
        numbers = []
        for file in files:
            parts = os.path.basename(file).split(' ')
            if len(parts) > 1 and parts[1].isdigit():
                numbers.append(int(parts[1]))
        return max(numbers) + 1 if numbers else 1

    def _ranked_output_root_for_queue(self, queue_id):
        """420 → 솔랭 폴더, 440 → 자유랭 폴더 (외부 큐면 솔랭과 동일 기본값)."""
        if queue_id == FLEX_RANK_QUEUE_ID:
            return FLEX_RANK_VIDEO_FOLDER
        return NEW_VIDEO_FOLDER

    def move_to_etc(self, video_path):
        if not video_path or not os.path.exists(video_path): return
        if not os.path.exists(ETC_VIDEO_FOLDER): os.makedirs(ETC_VIDEO_FOLDER)
        target = os.path.join(ETC_VIDEO_FOLDER, os.path.basename(video_path))
        try:
            shutil.move(video_path, target); print(f"📦 [기타] 영상 이동: {target}")
        except:
            pass

    def _request(self, url, params=None):
        headers = {"X-Riot-Token": self.api_key}
        try:
            res = requests.get(url, headers=headers, params=params)
            return res.json() if res.status_code == 200 else None
        except:
            return None

    @staticmethod
    def _my_puuid_in_match(match, puuids):
        """참가자 10명 중 내 계정 puuid. 한 판에 내 계정은 1개뿐."""
        if not match:
            return None
        participants = match.get("info", {}).get("participants") or []
        in_match = {p.get("puuid") for p in participants}
        for puuid in puuids:
            if puuid in in_match:
                return puuid
        return None

    def _fetch_match_with_retry(self, match_id, *, wait: bool):
        """
        gameId 를 아는 경우: 호출 1번으로 끝.

        게임 직후에는 매치가 아직 API 에 안 올라와 있을 수 있어,
        고정 대기 대신 짧게 재시도한다 (올라오는 즉시 진행).
        """
        deadline = time.time() + (MATCH_WAIT_TIMEOUT_SEC if wait else 0)
        while True:
            try:
                match = get_match_by_gameId(match_id)
            except Exception as e:
                print(f"  매치 조회 오류: {e}")
                match = None
            if match:
                return match
            if time.time() >= deadline:
                return None
            print(f"  아직 API 에 없음 → {MATCH_RETRY_INTERVAL_SEC}초 후 재시도")
            time.sleep(MATCH_RETRY_INTERVAL_SEC)

    def _find_match_with_retry(self, puuids, start_sec, end_sec, rec_end_ms, *, wait: bool):
        """gameId 가 없을 때: 녹화 시간대 검색을 매치가 올라올 때까지 재시도."""
        deadline = time.time() + (MATCH_WAIT_TIMEOUT_SEC if wait else 0)
        while True:
            result = self._find_match_in_window(puuids, start_sec, end_sec, rec_end_ms)
            if result[0] is not None:
                return result
            if time.time() >= deadline:
                return result
            print(f"  아직 API 에 없음 → {MATCH_RETRY_INTERVAL_SEC}초 후 재시도")
            time.sleep(MATCH_RETRY_INTERVAL_SEC)

    def _match_ids_in_window(self, puuid, start_sec, end_sec):
        """녹화 시간대에 걸치는 매치 ID만 조회 (계정당 1회 호출)."""
        return self._request(
            f"https://asia.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids",
            {
                "startTime": int(start_sec) - MATCH_SEARCH_MARGIN_SEC,
                "endTime": int(end_sec) + MATCH_SEARCH_MARGIN_SEC,
                "count": 5,
            },
        )

    def _best_match_among(self, match_ids, puuid, rec_end_ms):
        """매치 ID 들 중 녹화 종료 시각에 가장 가까운 매치."""
        best = (None, None, float("inf"))
        for m_id in match_ids:
            data = self._request(f"https://asia.api.riotgames.com/lol/match/v5/matches/{m_id}")
            if not data:
                continue
            diff = abs(rec_end_ms - data["info"]["gameEndTimestamp"])
            if diff < best[2]:
                best = (data, puuid, diff)
        return best

    def _find_match_in_window(self, puuids, start_sec, end_sec, rec_end_ms):
        """
        gameId 를 모를 때: 녹화 시간대에 걸치는 매치만 계정별로 조회.

        계정별 최근 10경기를 전부 받아오던 방식(계정 5개 = 55회 호출)을
        계정당 ID 조회 1회로 줄인다. 대부분 한 계정만 결과가 나온다.
        """
        candidates = []
        for puuid in puuids:
            for m_id in self._match_ids_in_window(puuid, start_sec, end_sec) or []:
                candidates.append((m_id, puuid))
        if not candidates:
            return None, None, float("inf")

        best = (None, None, float("inf"))
        for m_id, puuid in candidates:
            data, found_puuid, diff = self._best_match_among([m_id], puuid, rec_end_ms)
            if data is not None and diff < best[2]:
                best = (data, found_puuid, diff)
        return best

    def _find_match_by_scan(self, puuids, rec_end_ms):
        """예비 경로: 계정별 최근 10경기를 모두 확인 (느림)."""
        best = (None, None, float("inf"))
        for puuid in puuids:
            match_ids = self._request(
                f"https://asia.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids",
                {"start": 0, "count": 10},
            )
            if not match_ids:
                continue
            data, found_puuid, diff = self._best_match_among(match_ids, puuid, rec_end_ms)
            if data is not None and diff < best[2]:
                best = (data, found_puuid, diff)
        return best

    @staticmethod
    def _normalize_match_id(game_id) -> str:
        match_id = str(game_id).strip()
        if match_id.upper().startswith("KR_"):
            return match_id
        return f"KR_{match_id}"

    def process_ranked_match(
            self,
            recording_start_time_local,
            queue_id,
            recording_end_time_override=None,
            video_path_override=None,
            *,
            game_id_override=None,
            output_dir_override=None,
            game_num_override=None,
            skip_match_wait=False,
            open_video_override=None,
            skip_loading_overlay=False,
    ):
        """
        랭크 영상 저장 + 트림. queue_id 가 440이면 자유랭 폴더, 420이면 솔랭 폴더(sol NEW_VIDEO_FOLDER).
        - 앞: gameStartTimestamp 기준 TRIM_SECONDS_BEFORE_GAME_START 초 앞부터 (±TRIM_SKIP_IF_START_WITHIN_GAME_SEC 이내면 앞 트림 없음)
        - 뒤: 매치 gameEndTimestamp에 맞춤
        recording_end_time_override: 테스트 시 파일 mtime 등으로 매치 매칭에 사용 (기본: time.time())
        video_path_override: 특정 파일만 처리 (기본: 원본 폴더 최신 영상)
        game_id_override: 지정 시 해당 매치 API 로 직접 조회 (일괄 재처리용)
        output_dir_override / game_num_override: 저장 폴더·게임 번호 고정
        """
        output_root = self._ranked_output_root_for_queue(queue_id)
        label = "자유랭" if queue_id == FLEX_RANK_QUEUE_ID else "솔랭"
        video_file = video_path_override or self.get_most_recent_video()
        if not video_file or not os.path.exists(video_file):
            print("❌ [영상 처리] 원본 영상을 찾을 수 없습니다.")
            return

        try:
            with open("puuid_list.json", "r", encoding="utf-8") as f:
                puuids = json.load(f)
        except Exception:
            puuids = []

        selected_match = None
        selected_puuid = None
        min_diff = 0.0

        if game_id_override is not None:
            match_id = self._normalize_match_id(game_id_override)
            print(f"⏳ [영상 처리] 매치 API 조회 ({match_id})...")
            selected_match = self._fetch_match_with_retry(
                match_id, wait=not skip_match_wait
            )
            selected_puuid = self._my_puuid_in_match(selected_match, puuids)
            if selected_puuid is None:
                if selected_match:
                    print("⚠️ [영상 처리] 참가자 중 내 계정이 없음 → 녹화 시간대로 재검색")
                selected_match = None

        if selected_match is None:
            print("⏳ [영상 처리] 매치 데이터 조회 및 분석 중...")
            rec_end_sec = (
                recording_end_time_override if recording_end_time_override is not None else time.time()
            )
            rec_end_ms = rec_end_sec * 1000

            selected_match, selected_puuid, min_diff = self._find_match_with_retry(
                puuids,
                recording_start_time_local,
                rec_end_sec,
                rec_end_ms,
                wait=not skip_match_wait,
            )
            if selected_match is None:
                print("⏳ [영상 처리] 시간대 조회 실패 → 최근 경기 전체 확인")
                selected_match, selected_puuid, min_diff = self._find_match_by_scan(
                    puuids, rec_end_ms
                )

            if not selected_match or min_diff > 600000:
                print("⚠️ [영상 처리] 종료 시각과 맞는 매치를 찾지 못해 etc로 이동합니다.")
                self.move_to_etc(video_file)
                return

        parts = selected_match['info']['participants']
        me = next((p for p in parts if p['puuid'] == selected_puuid), None)
        if not me:
            print("❌ [영상 처리] 참가자 정보를 찾을 수 없습니다.")
            self.move_to_etc(video_file)
            return

        opponent = next(
            (p for p in parts if p['teamId'] != me['teamId'] and p['teamPosition'] == me['teamPosition']),
            None,
        )

        my_champ_kr = self.champ_map_eng_to_kr.get(me['championName'], me['championName'])
        op_champ_kr = (
            self.champ_map_eng_to_kr.get(opponent['championName'], opponent['championName'])
            if opponent
            else "Unknown"
        )
        kda = f"{me['kills']} {me['deaths']} {me['assists']}"
        game_id = selected_match['info']['gameId']
        participant_id = me['participantId']

        try:
            tier_raw = get_tier_detail_by_puuid(selected_puuid)
            tier_str = convert_tier_detail(tier_raw)
        except:
            tier_str = "Unranked"

        game_start_ms = selected_match['info']['gameStartTimestamp']
        game_end_ms = selected_match['info']['gameEndTimestamp']
        recording_start_sec = float(recording_start_time_local)
        game_start_sec = game_start_ms / 1000.0
        game_end_sec = game_end_ms / 1000.0

        delta_sec = game_start_sec - recording_start_sec
        if abs(delta_sec) <= TRIM_SKIP_IF_START_WITHIN_GAME_SEC:
            trim_start_sec = 0.0
        else:
            trim_start_sec = max(0.0, delta_sec - TRIM_SECONDS_BEFORE_GAME_START)

        span_rec_start_to_game_end_sec = game_end_sec - recording_start_sec
        final_duration_sec = span_rec_start_to_game_end_sec - trim_start_sec
        if final_duration_sec <= 0:
            print("❌ [영상 처리] 계산된 구간 길이가 0 이하입니다. 트림을 건너뜁니다.")
            self.move_to_etc(video_file)
            return

        base, _ext = os.path.splitext(video_file)
        temp_path = f"{base}_trimmed.mkv"
        overlay_path = f"{base}_overlay.png"
        rune_png_path = f"{base}_rune.png"

        print(
            f"✂️ 앞쪽 트림 {trim_start_sec:.2f}s, 길이 {final_duration_sec:.2f}s (게임종료까지)"
        )

        riot_id = get_summoner_name_by_puuid(selected_puuid)
        match_id = selected_match["metadata"]["matchId"]
        deeplol_url = build_deeplol_match_url(riot_id, match_id)
        overlay_ok = save_loading_overlay(
            match_id,
            overlay_path,
            deeplol_url=deeplol_url,
            match_info=selected_match["info"],
        )

        use_loading_overlay = (
            not skip_loading_overlay
            and delta_sec >= 0
            and overlay_ok
            and os.path.exists(overlay_path)
        )
        if delta_sec < 0 and not skip_loading_overlay:
            print("ℹ️ [로딩창] 게임 시작 후 녹화됨 → 로딩 오버레이 생략")

        try:
            if use_loading_overlay:
                rune_png = save_rune_overlay_png(me, rune_png_path)
                print(
                    f"🖼️ [합성] 로딩 {LOADING_OVERLAY_SEC:.0f}초(딥롤) + "
                    f"룬 {RUNE_OVERLAY_SEC:.0f}초"
                )
                try:
                    build_video_with_overlays(
                        video_file,
                        temp_path,
                        loading_overlay_png=overlay_path,
                        rune_overlay_png=rune_png,
                        game_pos_sec=delta_sec,
                        body_end_sec=span_rec_start_to_game_end_sec,
                    )
                except Exception as e:
                    print(f"⚠️ [합성] 실패, 트림만 수행: {e}")
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass
                    self.trim_video(video_file, temp_path, trim_start_sec, final_duration_sec)
            else:
                if not overlay_ok or not os.path.exists(overlay_path):
                    print("⚠️ [로딩창] 오버레이 없음 → 트림만 수행")
                else:
                    print("🎬 [로딩창] 오버레이 생략 → 트림만 수행")
                self.trim_video(video_file, temp_path, trim_start_sec, final_duration_sec)
        finally:
            for tmp_png in (overlay_path, rune_png_path):
                if os.path.exists(tmp_png):
                    try:
                        os.remove(tmp_png)
                    except OSError:
                        pass

        if not os.path.exists(temp_path):
            print("❌ [영상 처리] ffmpeg 출력 파일이 생성되지 않았습니다.")
            return

        g_date = datetime.datetime.fromtimestamp(game_start_ms / 1000)
        if g_date.hour < 6:
            g_date -= datetime.timedelta(days=1)
        date_str = g_date.strftime('%y%m%d')

        if output_dir_override:
            save_folder = output_dir_override
        else:
            save_folder = os.path.join(output_root, date_str)
        if not os.path.exists(save_folder):
            os.makedirs(save_folder)

        if game_num_override is not None:
            game_num = game_num_override
        else:
            game_num = self.get_next_game_number(date_str, output_root)
        new_name = (
            f"{date_str} {game_num:02d} {my_champ_kr} vs {op_champ_kr} {kda} {game_id} {participant_id} {tier_str}.mkv"
        )
        final_path = os.path.join(save_folder, new_name)

        os.rename(temp_path, final_path)
        print(f"✅ [{label}] 저장 완료: {final_path}")
        print(f"📁 원본 유지: {video_file}")
        should_open = OPEN_VIDEO if open_video_override is None else open_video_override
        if should_open:
            os.startfile(final_path)

    def process_solo_rank(
            self,
            recording_start_time_local,
            recording_end_time_override=None,
            video_path_override=None,
    ):
        """호환용: 솔로/듀오(420) 경로만 사용."""
        return self.process_ranked_match(
            recording_start_time_local,
            SOLO_DUO_QUEUE_ID,
            recording_end_time_override=recording_end_time_override,
            video_path_override=video_path_override,
        )