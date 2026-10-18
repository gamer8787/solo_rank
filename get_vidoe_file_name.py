import google_auth_oauthlib.flow
import googleapiclient.discovery

# 1. OAuth 2.0 인증 설정 (채널 소유자 권한 필요)
scopes = ["https://www.googleapis.com/auth/youtube.readonly"]
flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
    "client_secret.json", scopes
)
credentials = flow.run_local_server(port=0)

youtube = googleapiclient.discovery.build("youtube", "v3", credentials=credentials)

# 2. 내 채널의 비디오 ID 목록 (예시 ID들 입력)
video_ids = ["VIDEO_ID_1", "VIDEO_ID_2", "VIDEO_ID_3"]

# 3. fileDetails 파트 요청
request = youtube.videos().list(
    part="snippet,fileDetails",
    id=",".join(video_ids)
)
response = request.execute()

# 4. 원본 파일명 추출
for item in response.get("items", []):
    title = item["snippet"]["title"]
    # fileDetails.fileName에 원래 업로드했던 파일명이 들어있음
    original_filename = item.get("fileDetails", {}).get("fileName", "정보 없음")
    print(f"영상 제목: {title} | 원본 파일명: {original_filename}")