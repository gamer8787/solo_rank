"""업로드된 영상 목록에서 원본 .mkv 파일명으로 gameId·participantId 를 복원한다.

예약 처리 후 제목에서 gameId 가 빠져도, fileDetails.fileName 은
`260914 01 암베사 vs 나서스 13 4 4 8381457941 1 GM1 1353.mkv` 형식을 유지한다.
seok seok 채널 소유자 token.json 이 필요하다.
"""

from __future__ import annotations

import os
import re

from env import CHANNEL_ID
from youtube import authenticate_youtube

RAW_PATTERN = re.compile(
    r"^(\d{6}) (\d{1,2}) (.+?) vs (.+?) "
    r"(\d+) (\d+) (\d+) (\d{8,12}) (\d+) "
    r"((?:Unranked)|(?:[A-Z]{1,2}\d{1,2})(?: (\d{1,4}))?)$"
)


def parse_raw_name(name: str) -> dict | None:
    """업로드 당시 제목 또는 파일명(확장자 포함 가능)에서 정보 추출."""
    m = RAW_PATTERN.match(os.path.splitext(name)[0].strip())
    if not m:
        return None
    return {
        "date_str": m.group(1),
        "game_number": int(m.group(2)),
        "our_champion_name": m.group(3),
        "opponent_champion_name": m.group(4),
        "kills": int(m.group(5)),
        "deaths": int(m.group(6)),
        "assists": int(m.group(7)),
        "game_id": f"KR_{m.group(8)}",
        "participant_id": int(m.group(9)),
        "tier_full": m.group(10).strip(),
    }


def uploads_playlist_id(youtube, channel_id: str = CHANNEL_ID) -> str:
    res = youtube.channels().list(part="contentDetails", id=channel_id).execute()
    return res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


def list_upload_ids(youtube, playlist_id: str, limit: int) -> list[str]:
    ids: list[str] = []
    token = None
    while len(ids) < limit:
        res = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=min(50, limit - len(ids)),
            pageToken=token,
        ).execute()
        ids.extend(i["contentDetails"]["videoId"] for i in res["items"])
        token = res.get("nextPageToken")
        if not token:
            break
    return ids[:limit]


def fetch_videos(youtube, video_ids: list[str]) -> list[dict]:
    """videoId 목록 → 원본 파일명에서 gameId 를 복원한 dict 목록."""
    out: list[dict] = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        res = youtube.videos().list(
            part="snippet,status,contentDetails,fileDetails",
            id=",".join(chunk),
        ).execute()
        for item in res.get("items", []):
            title = item["snippet"]["title"]
            file_name = item.get("fileDetails", {}).get("fileName", "")
            info = parse_raw_name(file_name) or parse_raw_name(title)
            source = None
            if parse_raw_name(file_name):
                source = "fileName"
            elif parse_raw_name(title):
                source = "title"
            out.append({
                "video_id": item["id"],
                "title": title,
                "file_name": file_name,
                "privacy": item["status"]["privacyStatus"],
                "duration": item["contentDetails"]["duration"],
                "id_source": source,
                **(info or {}),
            })
    order = {v: n for n, v in enumerate(video_ids)}
    out.sort(key=lambda v: order.get(v["video_id"], 1 << 30))
    return out


def get_videos_on_date(yymmdd: str, max_scan: int = 400) -> list[dict]:
    """해당 날짜(YYMMDD) 원본 파일명 기준 업로드만, 판 번호 오름차순.

    업로드 순서는 경기 날짜와 다를 수 있어 since 조기 중단 없이 최근 max_scan 개를 훑는다.
    """
    if not os.path.exists("token.json"):
        raise FileNotFoundError(
            "seok seok 채널 token.json 이 필요합니다. "
            "채널 소유자 OAuth 토큰을 프로젝트 루트에 두세요."
        )
    youtube = authenticate_youtube()
    playlist_id = uploads_playlist_id(youtube)
    videos = fetch_videos(youtube, list_upload_ids(youtube, playlist_id, max_scan))
    out = [v for v in videos if v.get("date_str") == yymmdd]
    out.sort(key=lambda v: int(v.get("game_number") or 0))
    return out
