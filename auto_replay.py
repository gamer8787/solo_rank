import time
import pygetwindow as gw
from obswebsocket import obsws, requests, exceptions
import pygame

# OBS-WebSocket 서버 정보
host = "localhost"
port = 4455  # 최신 버전의 기본 포트
password = "your_password"  # OBS-WebSocket 설정에서 지정한 비밀번호

# pygame 초기화
pygame.mixer.init()

# WebSocket 연결
ws = obsws(host, port, password)
ws.connect()

def is_league_open():
    """League of Legends 창이 열려 있는지 확인"""
    league_windows = gw.getWindowsWithTitle('League of Legends (TM) Client')
    return len(league_windows) > 0

def play_sound(file):
    """소리 재생"""
    pygame.mixer.music.load(file)
    pygame.mixer.music.play()

try:
    was_recording = False

    while True:
        league_open = is_league_open()

        if league_open and not was_recording:
            print("League of Legends 창이 열려 있습니다. 녹화를 시작합니다.")
            play_sound('record.mp3')  # 녹화 시작 소리 재생
            ws.call(requests.StartRecord())
            was_recording = True

        elif not league_open and was_recording:
            print("League of Legends 창이 닫혀 있습니다. 녹화를 중지합니다.")
            ws.call(requests.StopRecord())
            play_sound('record.mp3')  # 녹화 종료 소리 재생
            was_recording = False

        # 5초마다 창 상태를 확인합니다.
        time.sleep(3)

except exceptions.OBSSDKError as e:
    print(f"OBS와의 통신 중 오류 발생: {e}")

finally:
    # OBS와의 연결 종료
    ws.disconnect()
    print("OBS WebSocket 연결이 종료되었습니다.")
    pygame.mixer.quit()
