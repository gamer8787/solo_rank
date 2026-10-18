이 폴더에는 main.py 실행 라인과 무관한 스크립트·샘플을 옮겨 두었습니다.

- auto_replay.py / auto_replay_test.py : 예전 단일 실행 스크립트
- 각종 테스트·실험용 .py 및 샘플(example.mp4, test.html 등)
- overlay.png (코드에서 참조하지 않던 루트 이미지)
- 깨진 이름의 알 수 없는 .bat 들

메인 기능: 프로젝트 루트에서
  python main.py
  또는
  python test_ranked_trim.py  (영상 테스트용)

예전 `_unused/auto_replay.py` 를 돌려보려면 반드시 **프로젝트 루트에서** 진행해야 modules, api 등을 찾습니다. 예시 (PowerShell):
  cd C:\\Users\\seok\\Desktop\\youtube\\auto_replay
  $env:PYTHONPATH="$PWD"; python _unused\\auto_replay.py --test-recent-original

유튜브 업데이트·썸네일은 make_thumbnail 등이 프로젝트 루트의 api/env/get_image/name_conversion 과 연결되어 있어 **루트에 그대로** 두었습니다.
