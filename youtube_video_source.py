"""업로드된 영상에서 gameId·participantId 를 복원한다.

예약 처리 후 유튜브 제목에는 gameId 가 빠져 있다.
채널 소유자 token.json 으로 fileDetails.fileName 을 읽으면
업로드 당시 파일명(`YYMMDD NN 챔프 vs 상대 K D A gameId participantId 티어`)이 그대로 남아 있다.
"""

from __future__ import annotations

import os
import re

from env import CHANNEL_ID
from youtube import authenticate_youtube

ROOT = os.path.dirname(os.path.abspath(__file__))

# gameId 자릿수는 8~12로 흔들릴 수 있어 고정 10자리에 묶지 않는다.
RAW_PATTERN = re.compile(
    r"^(\d{6}) (\d{1,2}) (.+?) vs (.+?) "
    r"(\d+) (\d+) (\d+) (\d{8,12}) (\d+)"
    r"(?:\s+((?:Unranked)|(?:[A-Z]{1,2}\d{1,2})(?:\s+\d{1,4})?))?"
    r"$"
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
        "kda_str": f"{m.group(5)}_{m.group(6)}_{m.group(7)}",
        "game_id": f"KR_{m.group(8)}",
        "participant_id": int(m.group(9)),
        "tier_full": (m.group(10) or "").strip(),
    }


def authenticate(token_path: str = "token.json"):
    """youtube.py 의 OAuth(token.json)로 채널 소유자 API 클라이언트를 만든다."""
    prev = os.getcwd()
    os.chdir(ROOT)
    try:
        token_file = token_path if os.path.isabs(token_path) else os.path.join(ROOT, token_path)
        if not os.path.exists(token_file) and not os.path.exists(os.path.join(ROOT, "client_secret.json")):
            raise FileNotFoundError(
                f"{token_file} / client_secret.json 이 없습니다. "
                "youtube.py 로 한 번 인증하면 token.json 이 생깁니다."
            )
        return authenticate_youtube()
    finally:
        os.chdir(prev)


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
    """videoId 목록 → 제목/원본 파일명/gameId 를 담은 dict 목록."""
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
            info = parse_raw_name(title) or parse_raw_name(file_name)
            source = None
            if parse_raw_name(title):
                source = "title"
            elif info:
                source = "fileName"
            out.append({
                "video_id": item["id"],
                "title": title,
                "file_name": file_name,
                "privacy": item["status"]["privacyStatus"],
                "duration": item["contentDetails"]["duration"],
                "published_at": item["snippet"]["publishedAt"],
                "id_source": source,
                **(info or {}),
            })
    order = {v: n for n, v in enumerate(video_ids)}
    out.sort(key=lambda v: order.get(v["video_id"], 1 << 30))
    return out


def get_recent_videos(count: int, token_path: str = "token.json") -> list[dict]:
    youtube = authenticate(token_path)
    playlist_id = uploads_playlist_id(youtube)
    return fetch_videos(youtube, list_upload_ids(youtube, playlist_id, count))


def get_videos_since(since_yymmdd: str, max_scan: int = 400, token_path: str = "token.json") -> list[dict]:
    """업로드 최신순으로 훑어 date_str 이 since_yymmdd 이상인 영상만 반환."""
    youtube = authenticate(token_path)
    playlist_id = uploads_playlist_id(youtube)
    videos = fetch_videos(youtube, list_upload_ids(youtube, playlist_id, max_scan))
    out: list[dict] = []
    for v in videos:
        ds = v.get("date_str")
        if not ds:
            continue
        if ds < since_yymmdd:
            break
        out.append(v)
    return out


def get_videos_on_date(yymmdd: str, max_scan: int = 400, token_path: str = "token.json") -> list[dict]:
    """해당 날짜(YYMMDD) 업로드만 판 번호 오름차순으로 반환.

    token.json 으로 fileDetails.fileName(원본 제목)에서 gameId 를 읽는다.
    업로드 순서는 경기 날짜와 다를 수 있어 since 조기 중단 없이 최근 max_scan 개를 훑는다.
    """
    youtube = authenticate(token_path)
    playlist_id = uploads_playlist_id(youtube)
    videos = fetch_videos(youtube, list_upload_ids(youtube, playlist_id, max_scan))
    out = [v for v in videos if v.get("date_str") == yymmdd]
    out.sort(key=lambda v: int(v.get("game_number") or 0))
    print(f"[YouTube] {yymmdd} 영상 {len(out)}개")
    return out


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="업로드 영상 제목/원본 파일명/gameId 확인")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--date", help="YYMMDD (예: 260913)")
    args = parser.parse_args()

    if args.date:
        videos = get_videos_on_date(args.date)
    else:
        videos = get_recent_videos(args.count)

    for i, v in enumerate(videos, 1):
        print(f"[{i}] videoId={v.get('video_id')}  ({v.get('privacy')}, {v.get('duration')})")
        print(f"    현재 제목  : {v.get('title')}")
        print(f"    원본 파일명: {v.get('file_name') or '(없음)'}")
        if v.get("game_id"):
            print(
                f"    game_id    : {v['game_id']}   participant_id: {v['participant_id']}   "
                f"(출처: {v.get('id_source')})"
            )
        else:
            print("    game_id    : 추출 실패")
        print()

    ok = sum(1 for v in videos if v.get("game_id"))
    print(f"총 {len(videos)}개 중 {ok}개 추출 성공")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
