import time
import multiprocessing
import asyncio
import threading
import requests
import urllib3
import psutil


# -------------------------------------------------------------
# [긴급 패치] lcu_driver 프로세스 충돌 방지 코드 (반드시 최상단 위치)
# -------------------------------------------------------------
# 라이브러리가 로드되기 전에 안전한 함수를 미리 정의합니다.
def _safe_return_ux_process():
    """
    LeagueClientUx 프로세스를 안전하게 찾는 함수 (psutil 에러 무시 버전)
    """
    for process in psutil.process_iter(['name', 'status']):
        try:
            if process.status() == psutil.STATUS_ZOMBIE:
                continue

            # 프로세스 이름 확인 (대소문자 구분 없이)
            if process.name() in ['LeagueClientUx.exe', 'LeagueClientUx']:
                yield process

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # 검사 도중 프로세스가 사라지면 무시하고 다음으로 넘어감
            continue


# 라이브러리 모듈을 수동으로 로드하여 강제 주입
import lcu_driver.utils
import lcu_driver.connector

# 두 곳 모두 덮어씌워서 어디서 호출하든 안전한 함수가 실행되게 함
lcu_driver.utils._return_ux_process = _safe_return_ux_process
lcu_driver.connector._return_ux_process = _safe_return_ux_process
# -------------------------------------------------------------

# 경고 제거
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 라이브러리 (패치 후 import)
from lcu_driver import Connector

try:
    from obswebsocket import requests as obs_requests
except ImportError:
    obs_requests = None

try:
    from obsws_python import ReqClient as obsws
except ImportError:
    from obswebsocket import obsws as obsws

# 모듈 Import
from env import OBS_HOST, OBS_PORT, OBS_PASSWORD
from modules.skill_overlay import show_overlay
from modules.champion_map import CHAMP_NAME_TO_ID
from modules.video_manager import VideoManager, RANKED_SAVE_QUEUE_IDS, FLEX_RANK_QUEUE_ID

# ---------------- 초기화 ----------------
connector = Connector()
vm = VideoManager()
ws = None

# 상태 변수
game_state = {
    "queueId": 0,
    "gameId": 0,
    "is_recording": False,
    "start_time": 0
}
overlay_process = None
parent_pipe = None


def _obs_start_stop_record(ws_client, start: bool):
    """호환: 레거시 obswebsocket .call 또는 obsws_python ReqClient .start_record / .stop_record"""
    if not ws_client:
        return False
    try:
        if obs_requests is not None and callable(getattr(ws_client, 'call', None)):
            req = obs_requests.StartRecord if start else obs_requests.StopRecord
            ws_client.call(req())
            return True
    except Exception:
        pass
    fn_name = 'start_record' if start else 'stop_record'
    fn = getattr(ws_client, fn_name, None)
    try:
        if callable(fn):
            fn()
            return True
    except Exception:
        pass
    return False


# ---------------- 오버레이 데이터 전송 로직 ----------------
def get_live_client_data():
    """인게임 API (Port 2999) 호출"""
    try:
        res = requests.get("https://127.0.0.1:2999/liveclientdata/playerlist", verify=False, timeout=1)
        return res.json() if res.status_code == 200 else []
    except:
        return []


def convert_data(live_data):
    """API 데이터 -> 오버레이 포맷 변환"""
    t1, t2 = [], []
    for p in live_data:
        raw = p.get('championName', '')
        key = raw.replace(" ", "").lower()

        # 정답표 매칭
        cid = CHAMP_NAME_TO_ID.get(raw, 0)
        if cid == 0: cid = CHAMP_NAME_TO_ID.get(key, 0)

        obj = {'championId': cid, 'summonerName': p.get('summonerName', ''), 'cellId': 0}
        if p.get('team') == 'ORDER':
            t1.append(obj)
        else:
            t2.append(obj)

    while len(t1) < 5: t1.append({'championId': 0, 'summonerName': ''})
    while len(t2) < 5: t2.append({'championId': 0, 'summonerName': ''})
    return t1, t2


async def overlay_updater(pipe):
    """오버레이 데이터 전송 (30초 후 중단)"""
    print("📡 [Main] 오버레이 데이터 전송 시작 (30초간 활성화)")
    start_loop_time = time.time()
    await asyncio.sleep(3)

    while True:
        if pipe.closed: break

        # 30초 지나면 API 호출 중단 (오버레이 고정)
        if time.time() - start_loop_time > 30:
            print(f"🔒 [Main] 30초 경과. 오버레이 업데이트를 중단하고 정보를 고정합니다.")
            break

        data = get_live_client_data()
        if data:
            t1, t2 = convert_data(data)
            try:
                pipe.send({'team_one': t1, 'team_two': t2})
            except:
                break
        await asyncio.sleep(1)


# ---------------- LCU 이벤트 핸들러 ----------------
@connector.ready
async def connect(connection):
    print("✅ Main System Ready. 롤 클라이언트 연결됨.")


@connector.ws.register('/lol-gameflow/v1/gameflow-phase', event_types=('UPDATE',))
async def gameflow_handler(connection, event):
    phase = event.data
    global overlay_process, parent_pipe, game_state

    # 1. 게임 시작
    if phase == 'InProgress' and not game_state['is_recording']:
        print("\n🎮 게임 진입! 시스템 가동...")

        # 오버레이 실행
        parent_pipe, child_pipe = multiprocessing.Pipe()
        overlay_process = multiprocessing.Process(target=show_overlay, args=(None, [], [], child_pipe))
        overlay_process.start()

        # 상태 설정
        game_state['start_time'] = time.time()
        game_state['is_recording'] = True

        try:
            session = await connection.request('get', '/lol-gameflow/v1/session')
            data = await session.json()
            game_state['queueId'] = data['gameData']['queue']['id']
            # gameId 를 알면 매치를 1번 호출로 가져올 수 있다 (계정 탐색 불필요)
            game_state['gameId'] = data['gameData'].get('gameId') or 0
        except:
            game_state['queueId'] = 0
            game_state['gameId'] = 0
        print(f"   queueId={game_state['queueId']} gameId={game_state['gameId']}")

        # 데이터 전송 및 녹화 시작
        asyncio.create_task(overlay_updater(parent_pipe))

        if ws:
            try:
                if _obs_start_stop_record(ws, True):
                    vm.play_sound('record.mp3')
                    print("⏺️ 녹화 시작됨")
                else:
                    print("⚠️ 녹화 시작 실패 (OBS API 인식 불가)")
            except:
                print("⚠️ 녹화 시작 실패")

    # 2. 게임 종료
    elif phase in ['EndOfGame', 'Lobby', 'None'] and game_state['is_recording']:
        print("\n🛑 게임 종료. 정리 작업 시작...")

        if overlay_process:
            overlay_process.terminate()
            overlay_process = None
        if parent_pipe:
            parent_pipe.close()

        if ws:
            try:
                if _obs_start_stop_record(ws, False):
                    vm.play_sound('record.mp3')
                    print("⏹️ 녹화 중지됨")
            except:
                pass

        # 후처리 (솔로/듀오 420, 자유랭 440)
        is_ranked_queue = game_state['queueId'] in RANKED_SAVE_QUEUE_IDS
        start_time = game_state['start_time']
        queue_id = game_state['queueId']
        game_id = game_state.get('gameId') or None

        def finalize_task():
            time.sleep(3)
            if is_ranked_queue:
                qid = queue_id
                label = "자유랭" if qid == FLEX_RANK_QUEUE_ID else "솔랭"
                print(f"⚔️ 랭크 매치({label}) → 트림·저장")
                vm.process_ranked_match(start_time, qid, game_id_override=game_id)
            else:
                print("📦 일반 게임 -> 단순 이동")
                vid = vm.get_most_recent_video()
                vm.move_to_etc(vid)

        threading.Thread(target=finalize_task).start()
        game_state['is_recording'] = False


# ---------------- 실행 진입점 ----------------
if __name__ == '__main__':
    multiprocessing.freeze_support()

    try:
        ws = obsws(OBS_HOST, OBS_PORT, OBS_PASSWORD)
        ws.connect()
        print("✅ OBS WebSocket 연결 성공")
    except:
        print("⚠️ OBS 연결 실패 (녹화 불가)")

    print("🚀 프로그램을 시작합니다...")

    # 여기서 에러가 나면 패치가 안 먹힌 것임
    connector.start()