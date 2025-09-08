import os

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request


# OAuth 2.0 클라이언트 시크릿 파일과 필요한 범위 설정
CLIENT_SECRETS_FILE = f"client_secret.json"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl"
]
def authenticate_youtube():
    """OAuth 2.0을 사용하여 YouTube API에 인증합니다."""
    creds = None

    # token.json 파일이 존재하면 자격 증명을 로드합니다.
    if os.path.exists(f"token.json"):
        try:
            creds = Credentials.from_authorized_user_file(f"token.json", SCOPES)
        except RefreshError:
            print("리프레시 토큰이 만료되었거나 유효하지 않습니다. 새로운 인증을 시도합니다.")
            os.remove(f"token.json")
            creds = None

    # 자격 증명이 없거나 유효하지 않으면 새로운 인증을 수행합니다.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                print("리프레시 토큰 갱신 실패. 새로운 인증을 시도합니다.")
                os.remove(f"token.json")
                creds = None

        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(f"token.json", "w") as token:
                token.write(creds.to_json())

    # YouTube API 클라이언트 생성
    youtube = build("youtube", "v3", credentials=creds)
    return youtube

if __name__ =="__main__":
    authenticate_youtube()