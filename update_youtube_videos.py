import time

import pytz
import re
import os

from api import get_match_info
from env import CHANNEL_ID
from make_thumbnail import create_thumbnail
from name_conversion import get_real_champion_name
from youtube import authenticate_youtube
from datetime import datetime, timedelta

def create_description(video, language):
    game_id = video['game_id']
    participant_id = video['participant_id']
    match_info = get_match_info(game_id, participant_id)

    champion_name = get_real_champion_name(match_info['championName'], language)
    opponent_champion_name = get_real_champion_name(match_info['opponentChampionName'], language)



    date_str = video['date_str']
    game_number_str = video['game_number']
    kda_str = video['kda_str']

    tier_full = video['tier_full']

    title = f"{date_str} {game_number_str} {champion_name} vs {opponent_champion_name} {kda_str} {tier_full}"

    # 언어별 간단한 설명 설정
    if language == "ko":
        description = "본채널 : https://www.youtube.com/channel/UCeV-ew08nfkEt9kkJ85sOSA"
    else:
        description = "Main Channel: https://www.youtube.com/channel/UCeV-ew08nfkEt9kkJ85sOSA"

    # ------------------------------
    # txt 파일 경로 (영상 파일명 기반)
    # ------------------------------
    # 영상 파일과 같은 위치에서 확장자만 txt로 변경
    base_path, _ = os.path.splitext(video['file_path'])
    txt_path = base_path + ".txt"
    # txt 파일이 있으면 내용 추가
    if os.path.exists(txt_path):
        with open(txt_path, "r", encoding="utf-8") as f:
            feedback_text = f.read().strip()
            print(feedback_text)
            if feedback_text:
                description += "\n\n" + feedback_text

    return title, description

def get_all_uploaded_videos(youtube, channel_id, max_results=100):
    """
    유튜브 채널의 업로드된 영상 정보를 파싱해서 리스트로 반환합니다.
    """
    request = youtube.channels().list(
        part="contentDetails",
        id=channel_id
    )
    response = request.execute()
    playlist_id = response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    videos = []
    pattern = (
        r"^(\d{6}) (\d{1,2}) (.+?) vs (.+?) "
        r"(\d+) (\d+) (\d+) (\d{10}) (\d+) "
        r"((?:Unranked)|(?:[A-Z]{1,2}\d{1,2}) (\d{1,4}))$"
    )

    fetched_results = 0
    next_page_token = None

    while fetched_results < max_results:
        current_max_results = min(max_results - fetched_results, 100)

        request = youtube.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=current_max_results,
            pageToken=next_page_token
        )
        response = request.execute()
        next_page_token = response.get("nextPageToken")

        for item in response.get("items", []):
            title = item["snippet"]["title"]
            video_id = item["snippet"]["resourceId"]["videoId"]

            match = re.match(pattern, title)
            if match:
                kills = match.group(5)
                deaths = match.group(6)
                assists = match.group(7)
                kda_str = f"{kills}_{deaths}_{assists}"

                # 티어 문자열 (예: "GM1 240")
                tier_group = match.group(10)

                if tier_group == "Unranked":
                    tier_full = "Unranked"
                else:
                    tier_full = tier_group  # "GM1 1083"


                # 로컬 파일 경로 (영상 저장된 폴더 기준)
                date_str = match.group(1)
                filename = f"{title}.mkv"  # 실제 업로드 전 영상 확장자
                file_path = os.path.join(f"C:/Users/seok/Videos/솔랭/{date_str}", filename)

                videos.append({
                    "video_id": video_id,
                    "date_str": date_str,
                    "game_number": int(match.group(2)),
                    "our_champion_name": match.group(3),
                    "opponent_champion_name": match.group(4),
                    "kda_str": kda_str,
                    "game_id": f"KR_{match.group(8)}",
                    "participant_id": int(match.group(9)),
                    "raw_title": title,
                    "file_path": file_path, # ✅ 여기 추가됨
                    "tier_full": tier_full
                })

        fetched_results += len(response.get("items", []))
        if not next_page_token:
            break
    return videos
def update_videos(youtube, videos):
    # 게임 순서 기준으로 정렬
    videos.sort(key=lambda v: (v["date_str"], v["game_number"]))
    # 예약 시간 기준 (1분 후부터 시작)
    base_time = datetime.now(pytz.timezone("Asia/Seoul")) + timedelta(minutes=1)

    for index, video in enumerate(videos):
        video_id = video["video_id"]
        game_id = video["game_id"]
        participant_id = video["participant_id"]
        category_id = "20"  # Gaming
        thumbnail_path = create_thumbnail(game_id,participant_id)
        tags = ["gameplay", "highlight", "gaming"]

        # 언어별 제목, 설명 생성
        ko_title, ko_description = create_description(video, "ko")
        en_title, en_description = create_description(video, "en")

        # 예약 시간 계산
        scheduled_time = base_time + timedelta(minutes=index)
        scheduled_time_iso = scheduled_time.isoformat()

        # 유튜브 video update 요청
        body = {
            "id": video_id,
            "localizations": {
                "ko": {"title": ko_title, "description": ko_description},
                "en": {"title": en_title, "description": en_description}
            },
            "snippet": {
                "title": ko_title,
                "description": ko_description,
                "categoryId": category_id,
                "tags": tags,
                "defaultLanguage": "ko"
            },
            "status": {
                "privacyStatus": "private",
                "publishAt": scheduled_time_iso,
                "selfDeclaredMadeForKids": False,
                "embeddable": True  # ✅ 이 줄을 추가하세요!
            }
        }

        # 영상 정보 업데이트
        youtube.videos().update(
            part="snippet,status,localizations",
            body=body
        ).execute()

        # 썸네일 업로드
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=thumbnail_path
        ).execute()

        print(f"[{index+1}] 예약됨: {ko_title} | 예약 시각: {scheduled_time.strftime('%Y-%m-%d %H:%M:%S')}")
        time.sleep(15) #rate limit
def apply_video():
    youtube = authenticate_youtube()
    channel_id = CHANNEL_ID
    videos = get_all_uploaded_videos(youtube, channel_id, max_results=100)
    total_videos = len(videos)
    print(f"{total_videos}개 비디오")
    update_videos(youtube, videos)

if __name__ =="__main__":
    apply_video()
