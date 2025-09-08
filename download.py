import yt_dlp

# 다운로드 옵션 설정
ydl_opts = {
    'outtmpl': '%(title)s.%(ext)s',  # 파일 이름 형식
    'format': 'bestvideo+bestaudio/best',  # 최고 화질 + 최고 음질
    'merge_output_format': 'mp4',  # 병합 후 mp4로 저장
    'cookies': 'cookies.txt',  # 로그인 쿠키 (본인 계정 영상이면 필수)
}

url = 'https://www.youtube.com/watch?v=영상ID'  # 유튜브 영상 URL

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    ydl.download([url])
