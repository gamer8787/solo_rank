from pydub import AudioSegment
import os

# 오디오 파일 로드
audio = AudioSegment.from_mp3("sound.mp3")

# 세그먼트 길이 설정 (0.3초 = 300ms)
segment_length = 700

# 오디오 파일 길이(밀리초 단위)
audio_length = len(audio)

# 세그먼트 저장 디렉토리 설정
output_dir = "output_segments"
os.makedirs(output_dir, exist_ok=True)

# 세그먼트 나누기 및 저장
for i in range(0, audio_length, segment_length):
    segment = audio[i:i + segment_length]
    segment.export(f"{output_dir}/segment_{i//segment_length + 1}.mp3", format="mp3")

print(f"{audio_length // segment_length} 개의 세그먼트가 {output_dir} 폴더에 저장되었습니다.")
