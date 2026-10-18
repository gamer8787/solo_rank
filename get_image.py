import io
import json
import urllib.request

from PIL import Image

from env import (
    DDRAGON_USER_AGENT,
    ddragon_unversioned_img_root,
    ddragon_versioned_cdn_root,
    get_data_dragon_version,
)

STAT_RUNE_MAP = {
    5008: "StatModsAdaptiveForceIcon.png",
    5005: "StatModsAttackSpeedIcon.png",
    5007: "StatModsCDRScalingIcon.png",
    5010: "StatModsMovementSpeedIcon.png",
    5013: "StatModsTenacityIcon.png",
    5011: "StatModsHealthScalingIcon.png",
    5001: "StatModsHealthPlusIcon.png",
}

_rune_json_cache: list | None = None
_rune_json_ver: str | None = None
_spell_json_cache: dict | None = None
_spell_json_ver: str | None = None


def _sanitize_champion_name(name: str) -> str:
    """
    DDragon은 대소문자를 엄격하게 구분합니다.
    'FiddleSticks'로 들어올 경우 'Fiddlesticks'로 교정합니다.
    """
    if name == "FiddleSticks":
        return "Fiddlesticks"
    return name

def _ddragon_read(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": DDRAGON_USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _image_from_url(url: str) -> Image.Image:
    return Image.open(io.BytesIO(_ddragon_read(url)))


def get_item_image(item_id):
    root = ddragon_versioned_cdn_root()
    url = f"{root}/img/item/{item_id}.png"
    return _image_from_url(url)


# --- 챔피언 관련 함수들에 보정 로직 적용 ---

def get_champion_loading_image(champion_name):
    champion_name = _sanitize_champion_name(champion_name) # 이름 보정
    root = ddragon_unversioned_img_root()
    url = f"{root}/champion/loading/{champion_name}_0.jpg"
    return _image_from_url(url)

def get_champion_splash_image(champion_name):
    champion_name = _sanitize_champion_name(champion_name) # 이름 보정
    root = ddragon_unversioned_img_root()
    url = f"{root}/champion/splash/{champion_name}_0.jpg"
    return _image_from_url(url)

def get_champion_image(champion_name):
    champion_name = _sanitize_champion_name(champion_name) # 이름 보정
    root = ddragon_versioned_cdn_root()
    url = f"{root}/img/champion/{champion_name}.png"
    return _image_from_url(url)

def get_champion_tile_image(champion_name):
    champion_name = _sanitize_champion_name(champion_name) # 이름 보정
    root = ddragon_unversioned_img_root()
    url = f"{root}/champion/tiles/{champion_name}_0.jpg"
    return _image_from_url(url)


def load_rune_data():
    global _rune_json_cache, _rune_json_ver
    v = get_data_dragon_version()
    if _rune_json_cache is None or _rune_json_ver != v:
        url = f"https://ddragon.leagueoflegends.com/cdn/{v}/data/en_US/runesReforged.json"
        _rune_json_cache = json.loads(_ddragon_read(url).decode("utf-8"))
        _rune_json_ver = v
    return _rune_json_cache


def get_rune_image(rune_id):
    rune_data = load_rune_data()
    img_root = ddragon_unversioned_img_root()
    for rune_tree in rune_data:
        if rune_tree["id"] == rune_id:
            url = f"{img_root}/{rune_tree['icon']}"
            return _image_from_url(url)
        for slot in rune_tree["slots"]:
            for rune in slot["runes"]:
                if rune["id"] == rune_id:
                    url = f"{img_root}/{rune['icon']}"
                    return _image_from_url(url)

    raise ValueError(f"Rune with ID {rune_id} not found in the data.")


def get_stat_rune_image(rune_id):
    if rune_id in STAT_RUNE_MAP:
        fn = STAT_RUNE_MAP[rune_id]
        url = f"{ddragon_unversioned_img_root()}/perk-images/StatMods/{fn}"
        return _image_from_url(url)
    raise ValueError(f"Invalid rune ID: {rune_id}")


def load_spell_data():
    global _spell_json_cache, _spell_json_ver
    v = get_data_dragon_version()
    if _spell_json_cache is None or _spell_json_ver != v:
        url = f"https://ddragon.leagueoflegends.com/cdn/{v}/data/ko_KR/summoner.json"
        _spell_json_cache = json.loads(_ddragon_read(url).decode("utf-8"))
        _spell_json_ver = v
    return _spell_json_cache


def get_spell_name(spell_id):
    spell_data = load_spell_data()
    for spell in spell_data["data"].values():
        if int(spell["key"]) == int(spell_id):
            return spell["image"]["full"]
    raise KeyError(f"Key '{spell_id}' not found in the summoner data.")


def get_spell_image(spell_id):
    spell_name = get_spell_name(spell_id)
    root = ddragon_versioned_cdn_root()
    url = f"{root}/img/spell/{spell_name}"
    return _image_from_url(url)
