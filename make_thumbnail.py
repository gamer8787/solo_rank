import os

from env import FONT_PATH
from get_image import get_champion_splash_image, get_champion_loading_image, get_item_image, get_rune_image, \
    get_spell_image, get_champion_tile_image, get_champion_image
from PIL import Image, ImageFilter, ImageDraw, ImageFont

from name_conversion import get_real_champion_name
from api import get_match_info
# text_gradient.py에서 가져온 함수들
from text_gradient import draw_text_with_shadow_and_border, apply_image_gradient_to_text, create_gradient_background


def create_thumbnail(gameId, participantId):
    # 필요한 정보 가져오기
    match_info = get_match_info(gameId, participantId)

    # match_info 딕셔너리에서 필요한 정보 풀어내기
    champion_name = match_info['championName']
    opponent_champion_name = match_info['opponentChampionName']
    kills = match_info['kills']
    deaths = match_info['deaths']
    assists = match_info['assists']
    itemlist = match_info['itemlist']
    primary_rune = match_info['primaryrune']
    sub_rune = match_info['subrune']
    game_version = match_info['gameVersion']  # 패치 버전 가져오기

    kda = f"{kills}/{deaths}/{assists}"
    # 아이템 이미지를 최대 3개까지 가져오기
    item_images = [get_item_image(item).convert("RGBA") for item in itemlist[:5]]
    rune_image = get_rune_image(primary_rune).convert("RGBA")
    sub_rune_image = get_rune_image(sub_rune).convert("RGBA")

    # 이미지 로드
    champion_splash_img = get_champion_splash_image(champion_name).convert("RGBA")
    champion_img = get_champion_image(champion_name).convert("RGBA")
    opponent_img = get_champion_image(opponent_champion_name).convert("RGBA")

    # 스플래시 이미지(배경)에 블러 효과 적용
    blurred_splash_img = champion_splash_img.filter(ImageFilter.GaussianBlur(0))  # 블러 강도는 radius 값으로 조절

    # 타일 이미지 크기 조정 (예: 배경 너비의 15% 정도)
    tile_width = int(blurred_splash_img.width * 0.15)
    champion_img = champion_img.resize(
        (tile_width, int(tile_width * (champion_img.height / champion_img.width))))
    opponent_img = opponent_img.resize(
        (tile_width, int(tile_width * (opponent_img.height / opponent_img.width))))

    # 배경 전체 크기 기준
    image_width, image_height = blurred_splash_img.size
    tile_width, tile_height = champion_img.size

    # 여백 및 위치 조정값
    margin = 150  # 이미지 바깥 여백
    top_offset = 100  # 위에서 약간 내려서 배치

    # 내 챔피언 타일 이미지 위치 (왼쪽 여백에 고정)
    champion_tile_position = (margin, top_offset)

    # 상대 챔피언 타일 이미지 위치 (오른쪽 여백 기준 정렬)
    opponent_tile_position = (image_width - tile_width - margin, top_offset)

    # 이미지 붙이기
    blurred_splash_img.paste(champion_img, champion_tile_position, champion_img)
    blurred_splash_img.paste(opponent_img, opponent_tile_position, opponent_img)

    # 폰트 설정 (기본 폰트를 사용하거나, 경로를 지정하여 다른 폰트를 사용할 수 있습니다)
    try:
        font = ImageFont.truetype(FONT_PATH, size=120)
        small_font = ImageFont.truetype(FONT_PATH, size=80)  # KDA 텍스트에 사용할 작은 폰트
        vs_font = ImageFont.truetype(FONT_PATH, size=90)  # VS 텍스트에 사용할 폰트
        patch_font = ImageFont.truetype(FONT_PATH, size=40)  # 패치 버전 텍스트에 사용할 작은 폰트
    except IOError as e:
        raise RuntimeError(f"Failed to load font from {FONT_PATH}") from e

    # 텍스트 위치 계산
    kda_text_position = (margin, 280)  # KDA 텍스트 위치
    item_position = (margin, 400)  # 아이템 이미지 위치 (KDA 텍스트 아래)

    # 패치 버전 텍스트 위치 계산 (오른쪽 위)
    patch_text_position = (margin, 20)  # 이미지 오른쪽 상단에 배치

    draw = ImageDraw.Draw(blurred_splash_img)  # 이미지 위에 텍스트 그리기용 객체 생성

    # 텍스트 크기 측정 (textbbox는 텍스트의 경계 사각형을 반환)
    bbox = draw.textbbox((0, 0), "VS", font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # 두 타일 중심 좌표 계산
    tile_width, tile_height = champion_img.size  # 두 타일 이미지의 크기
    champion_center_x = champion_tile_position[0] + tile_width // 2
    opponent_center_x = opponent_tile_position[0] + tile_width // 2
    center_x = (champion_center_x + opponent_center_x) // 2
    # 텍스트 왼쪽 위 좌표 (텍스트 중심이 정확히 두 이미지 사이 중앙에 오도록)
    vs_text_position = (
        center_x - text_width // 2 + 12,
        top_offset + 30  # 살짝 아래로 보정
    )
    # 그라디언트 배경 생성 (예시: 흰색에서 검은색으로)

    gradient_image = create_gradient_background((800, 400), start_color=(255, 255, 255), end_color=(127, 127, 127))
    gradient_image2 = create_gradient_background((800, 400), start_color=(127, 127, 127), end_color=(0, 0, 0))

    # 텍스트 추가 (Champion Name, KDA, VS) - 그림자 및 테두리 포함
    draw_text_with_shadow_and_border(blurred_splash_img, kda_text_position, kda, small_font, shadow_color="black", shadow_offset=(3, 3), shadow_blur_radius=3, border_color="black", border_width=1)
    draw_text_with_shadow_and_border(blurred_splash_img, vs_text_position, "VS", vs_font, shadow_color="black", shadow_offset=(3, 3), shadow_blur_radius=3, border_color="black", border_width=1)

    # 텍스트에 그라디언트 이미지 적용
    apply_image_gradient_to_text(blurred_splash_img, kda_text_position, kda, small_font, gradient_image)
    apply_image_gradient_to_text(blurred_splash_img, vs_text_position, "VS", vs_font, gradient_image)

    # 패치 버전에 그라디언트 이미지 적용
    patch_version_numbers = ".".join(game_version.split(".")[:2])
    apply_image_gradient_to_text(blurred_splash_img, patch_text_position, patch_version_numbers, patch_font, gradient_image2)

    # 아이템 이미지를 kda 텍스트 아래에 추가
    current_x = item_position[0]
    item_y_position = item_position[1]
    for item_img in item_images:
        item_img = item_img.resize((130, 130))  # 아이템 이미지 크기 조정
        blurred_splash_img.paste(item_img, (current_x, item_y_position), item_img)
        current_x += item_img.width + 10  # 다음 아이템 이미지 위치 계산 (여백 포함)

    # 룬 이미지 추가 (아이템 이미지 아래)
    rune_img_y_position = item_y_position + 140  # 아이템 이미지 아래에 룬 이미지 배치
    rune_image = rune_image.resize((130, 130))  # 룬 이미지 크기 조정
    blurred_splash_img.paste(rune_image, (margin, rune_img_y_position), rune_image)

    sub_rune_image = sub_rune_image.resize((90, 90))  # 룬 이미지 크기 조정
    blurred_splash_img.paste(sub_rune_image, (margin + 160, rune_img_y_position+30), sub_rune_image)

    output_image_path = f"thumbnail/{gameId}_{participantId}.png"
    blurred_splash_img.save(output_image_path)
    # blurred_splash_img.show()
    return output_image_path

# 실행 예시
if __name__ =="__main__":
    create_thumbnail("KR_7678970736", 6)
