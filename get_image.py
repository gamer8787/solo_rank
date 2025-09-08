import os
import json
from PIL import Image, ImageDraw, ImageOps, ImageEnhance, ImageFilter, ImageFont

from env import ITEM_FOLDER, CHAMPION_FOLDER, RUNE_JSON_PATH, RUNE_IMAGE_FOLDER, STAT_RUNE_FOLDER, SPELL_JSON_PATH, \
    SPELL_IMAGE_PATH, CHAMPION_FOLDER2

STAT_RUNE_MAP = {
    5008: "StatModsAdaptiveForceIcon.png",
    5005: "StatModsAttackSpeedIcon.png",
    5007: "StatModsCDRScalingIcon.png",
    5010: "StatModsMovementSpeedIcon.png",
    5013: "StatModsTenacityIcon.png",
    5011: "StatModsHealthScalingIcon.png",
    5001: "StatModsHealthPlusIcon.png",
}

def get_item_image(item_id):
    image_path = os.path.join(ITEM_FOLDER, f"{item_id}.png")

    # 이미지가 해당 경로에 존재하는지 확인합니다.
    if os.path.exists(image_path):
        # 이미지를 열고 반환합니다.
        return Image.open(image_path)
    else:
        # 이미지가 존재하지 않을 경우 예외를 발생시킵니다.
        raise FileNotFoundError(f"loading Image for item_id {item_id} not found at {image_path}")
def get_champion_loading_image(champion_name):
    # 챔피언 이미지 파일 경로를 생성합니다.
    image_path = os.path.join(CHAMPION_FOLDER, "loading", f"{champion_name}_0.jpg")

    # 이미지가 해당 경로에 존재하는지 확인합니다.
    if os.path.exists(image_path):
        # 이미지를 열고 반환합니다.
        return Image.open(image_path)
    else:
        # 이미지가 존재하지 않을 경우 예외를 발생시킵니다.
        raise FileNotFoundError(f"loading Image for champion {champion_name} not found at {image_path}")

def get_champion_splash_image(champion_name):
    # 챔피언 이미지 파일 경로를 생성합니다.
    image_path = os.path.join(CHAMPION_FOLDER, "splash", f"{champion_name}_0.jpg")

    # 이미지가 해당 경로에 존재하는지 확인합니다.
    if os.path.exists(image_path):
        # 이미지를 열고 반환합니다.
        return Image.open(image_path)
    else:
        # 이미지가 존재하지 않을 경우 예외를 발생시킵니다.
        raise FileNotFoundError(f"Splash Image for champion {champion_name} not found at {image_path}")

def get_champion_image(champion_name):
    # 챔피언 이미지 파일 경로를 생성합니다.
    image_path = os.path.join(CHAMPION_FOLDER2, f"{champion_name}.png")

    # 이미지가 해당 경로에 존재하는지 확인합니다.
    if os.path.exists(image_path):
        # 이미지를 열고 반환합니다.
        return Image.open(image_path)
    else:
        # 이미지가 존재하지 않을 경우 예외를 발생시킵니다.
        raise FileNotFoundError(f"Tile Image for champion {champion_name} not found at {image_path}")
def get_champion_tile_image(champion_name):
    # 챔피언 이미지 파일 경로를 생성합니다.
    image_path = os.path.join(CHAMPION_FOLDER, "tiles", f"{champion_name}_0.jpg")

    # 이미지가 해당 경로에 존재하는지 확인합니다.
    if os.path.exists(image_path):
        # 이미지를 열고 반환합니다.
        return Image.open(image_path)
    else:
        # 이미지가 존재하지 않을 경우 예외를 발생시킵니다.
        raise FileNotFoundError(f"Tile Image for champion {champion_name} not found at {image_path}")



def load_rune_data():
    with open(RUNE_JSON_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)
def get_rune_image(rune_id):
    rune_data = load_rune_data()
    # rune_id를 통해 해당 룬을 검색합니다.
    for rune_tree in rune_data:
        if rune_tree['id'] == rune_id:
            # 아이콘 경로 생성
            icon_path = os.path.join(RUNE_IMAGE_FOLDER, rune_tree['icon'])

            # 이미지 파일이 존재하는지 확인
            if os.path.exists(icon_path):
                return Image.open(icon_path)
        for slot in rune_tree['slots']:
            for rune in slot['runes']:
                if rune['id'] == rune_id:
                    # 아이콘 경로 생성
                    icon_path = os.path.join(RUNE_IMAGE_FOLDER, rune['icon'])

                    # 이미지 파일이 존재하는지 확인
                    if os.path.exists(icon_path):
                        return Image.open(icon_path)
                    else:
                        raise FileNotFoundError(f"Rune icon for ID {rune_id} not found at {icon_path}")

    raise ValueError(f"Rune with ID {rune_id} not found in the data.")
def get_stat_rune_image(rune_id):
    if rune_id in STAT_RUNE_MAP:
        image_filename = STAT_RUNE_MAP[rune_id]
        image_path = os.path.join(STAT_RUNE_FOLDER, image_filename)
        if os.path.exists(image_path):
            return Image.open(image_path)
        else:
            raise FileNotFoundError(f"Image file not found: {image_path}")
    else:
        raise ValueError(f"Invalid rune ID: {rune_id}")
def load_spell_data():
    with open(SPELL_JSON_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)
def get_spell_name(spell_id):
    spell_data = load_spell_data()
    # 'data' 항목에서 주어진 key 값을 찾아 'image'의 'full' 값을 반환
    for spell in spell_data['data'].values():
        if int(spell['key']) == int(spell_id):
            return spell['image']['full']
    # 해당하는 key 값을 찾지 못한 경우 KeyError 예외 발생
    raise KeyError(f"Key '{spell_id}' not found in the summoner data.")

def get_spell_image(spell_id):
    spell_name = get_spell_name(spell_id)
    image_path = os.path.join(SPELL_IMAGE_PATH, spell_name);

    # 이미지가 해당 경로에 존재하는지 확인합니다.
    if os.path.exists(image_path):
        # 이미지를 열고 반환합니다.
        return Image.open(image_path)
    else:
        # 이미지가 존재하지 않을 경우 예외를 발생시킵니다.
        raise FileNotFoundError(f"loading Image for spell_id {spell_id} not found at {image_path}")
