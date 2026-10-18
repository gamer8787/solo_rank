import re
import time
import os
from urllib.parse import quote, unquote

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

from api import get_match_by_gameId, get_tier_detail_by_puuid, convert_tier_detail
from env import PROJECT_ROOT

# 1. 1920x1080 해상도 기준 챔피언 카드 중앙 (X, Y) 픽셀 좌표
COORDINATES = {
    "블루팀 1번": (368, 288), "블루팀 2번": (664, 288), "블루팀 3번": (960, 288), "블루팀 4번": (1256, 288), "블루팀 5번": (1552, 288),
    "레드팀 1번": (368, 800), "레드팀 2번": (664, 800), "레드팀 3번": (960, 800), "레드팀 4번": (1256, 800), "레드팀 5번": (1552, 800),
}

TIER_Y_OFFSET = -85
BADGE_Y_OFFSET = -15
NAME_Y_OFFSET = 50

COLOR_CHALLENGER = "#F0B429"
COLOR_GRANDMASTER = "#E08E8E"
COLOR_MASTER = "#C9A0E8"
COLOR_UNRANK = "#C8C8C8"
COLOR_DEFAULT_TIER = "#FFFFFF"
COLOR_STREAMER = "#FF5555"
COLOR_PRO = "#7B8CDB"
COLOR_NAME = "#FFFFFF"
COLOR_ATTRIBUTION = "#AEAEAE"
ATTRIBUTION_TEXT = "출처: DEEPLOL"
ATTRIBUTION_POS = (960, 520)

LOADING_POSITION_ORDER = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
BLUE_TEAM_ID = 100
RED_TEAM_ID = 200

HAN_CHAR_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
CJK_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
]


def _is_han_char(ch: str) -> bool:
    return bool(HAN_CHAR_RE.match(ch))


def segment_text_mixed(text: str) -> list[tuple[str, bool]]:
    """공백·문자 종류 기준으로 (조각, 한자폰트 사용 여부) 분리."""
    if not text:
        return []
    segments: list[tuple[str, bool]] = []
    for token in re.split(r"(\s+)", text):
        if not token:
            continue
        if token.isspace() or not any(_is_han_char(c) for c in token):
            segments.append((token, False))
            continue
        run: list[str] = []
        use_cjk = _is_han_char(token[0])
        for ch in token:
            ch_cjk = _is_han_char(ch)
            if ch_cjk == use_cjk:
                run.append(ch)
            else:
                segments.append(("".join(run), use_cjk))
                run = [ch]
                use_cjk = ch_cjk
        if run:
            segments.append(("".join(run), use_cjk))
    return segments


def _load_truetype(size: int, *paths: str) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in paths:
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _load_cjk_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return _load_truetype(size, *CJK_FONT_CANDIDATES)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    if not text:
        return 0.0
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def draw_text_mixed_center(
    draw: ImageDraw.ImageDraw,
    pos: tuple[int, int],
    text: str,
    font_primary,
    font_cjk,
    *,
    fill: str,
    stroke_width: int = 0,
    stroke_fill: str = "black",
) -> None:
    """한자 포함 구간만 CJK 폰트로, 나머지는 기본 폰트로 가운데 정렬."""
    segments = segment_text_mixed(text)
    if not segments:
        return
    if len(segments) == 1 and not segments[0][1]:
        draw.text(
            pos, text, font=font_primary, fill=fill,
            anchor="mm", stroke_width=stroke_width, stroke_fill=stroke_fill,
        )
        return

    x, y = pos
    total_w = sum(
        _text_width(draw, seg, font_cjk if use_cjk else font_primary)
        for seg, use_cjk in segments
    )
    cursor_x = x - total_w / 2
    for seg, use_cjk in segments:
        font = font_cjk if use_cjk else font_primary
        draw.text(
            (cursor_x, y), seg, font=font, fill=fill,
            anchor="lm", stroke_width=stroke_width, stroke_fill=stroke_fill,
        )
        cursor_x += _text_width(draw, seg, font)


def normalize_match_id(game_id) -> str:
    match_id = str(game_id).strip()
    if match_id.upper().startswith("KR_"):
        return match_id
    return f"KR_{match_id}"


def parse_match_id_from_deeplol_url(url: str) -> str | None:
    match = re.search(r"/matches/(KR_\d+)", url, re.IGNORECASE)
    return match.group(1) if match else None


def build_deeplol_match_url(riot_id, game_id, region="kr"):
    game_name, tag_line = riot_id.split("#", 1)
    slug = quote(f"{game_name}-{tag_line}", safe="-")
    match_key = normalize_match_id(game_id)
    return f"https://www.deeplol.gg/summoner/{region.lower()}/{slug}/matches/{match_key}"


def normalize_riot_id_key(riot_id: str | None) -> str:
    if not riot_id or "#" not in riot_id:
        return ""
    game_name, tag_line = riot_id.rsplit("#", 1)
    return f"{game_name.strip().lower()}#{tag_line.strip().lower()}"


def lookup_badge(badge_map: dict, riot_id: str | None) -> dict:
    if not riot_id or not badge_map:
        return {}
    if riot_id in badge_map:
        return badge_map[riot_id]
    return badge_map.get(normalize_riot_id_key(riot_id), {})


def parse_riot_id_from_href(href):
    if not href or "/summoner/" not in href.lower():
        return None
    path = href.split("/summoner/", 1)[-1]
    parts = path.split("/", 1)
    if len(parts) < 2:
        return None
    name_part = unquote(parts[1])
    if "-" not in name_part:
        return None
    game_name, tag_line = name_part.rsplit("-", 1)
    game_name = game_name.strip()
    tag_line = tag_line.strip()
    if not game_name or not tag_line:
        return None
    return f"{game_name}#{tag_line}"


def riot_id_from_participant(participant: dict) -> str | None:
    game_name = participant.get("riotIdGameName") or participant.get("summonerName") or ""
    tag_line = participant.get("riotIdTagline") or participant.get("riotIdTagLine") or ""
    game_name = str(game_name).strip()
    tag_line = str(tag_line).strip()
    if game_name and tag_line:
        return f"{game_name}#{tag_line}"
    return None


def _loading_sort_key(participant: dict):
    pos = participant.get("teamPosition") or participant.get("individualPosition") or ""
    if pos in LOADING_POSITION_ORDER:
        return LOADING_POSITION_ORDER.index(pos)
    return 100 + participant.get("participantId", 0)


def _team_participants_for_loading(participants: list, team_id: int) -> list:
    team = [p for p in participants if p.get("teamId") == team_id]
    team.sort(key=_loading_sort_key)
    return team[:5]


def format_tier_for_overlay(tier_detail_str):
    if tier_detail_str.strip().lower() == "unranked":
        return "Unrank"
    converted = convert_tier_detail(tier_detail_str)
    if converted == "Unranked":
        return "Unrank"
    parts = converted.split()
    if len(parts) == 2:
        return f"{parts[0]}-{parts[1]}"
    return converted


def tier_text_color(tier_display):
    if tier_display == "Unrank":
        return COLOR_UNRANK
    if tier_display.startswith("GM"):
        return COLOR_GRANDMASTER
    if tier_display.startswith("C"):
        return COLOR_CHALLENGER
    if tier_display.startswith("M"):
        return COLOR_MASTER
    return COLOR_DEFAULT_TIER


def badge_text_color(label):
    if label == "STRM":
        return COLOR_STREAMER
    if label == "PRO":
        return COLOR_PRO
    return COLOR_DEFAULT_TIER


def fetch_tier_display_by_puuid(puuid: str):
    try:
        tier_detail = get_tier_detail_by_puuid(puuid)
        return format_tier_for_overlay(tier_detail)
    except Exception as e:
        print(f"  ⚠ 티어 조회 실패 ({puuid[:8]}…): {e}")
        return None


def _has_icon_src(src: str | None, kind: str) -> bool:
    return bool(src and f"icon_small_{kind}" in src.lower())


def _find_player_row(link, team_boundary):
    """소환사 링크 1개만 담긴 가장 작은 div 행 (딥롤 UI 변경 대응)."""
    node = link.parent
    best = None
    while node and node is not team_boundary:
        if node.name == "div":
            links = node.find_all("a", href=lambda h: h and "/summoner/" in h.lower())
            if len(links) == 1:
                best = node
        node = node.parent
    return best or link.parent


def _extract_badge_from_row(row, link) -> dict | None:
    is_streamer = row.find("img", src=lambda s: _has_icon_src(s, "streamer"))
    is_pro = row.find("img", src=lambda s: _has_icon_src(s, "pro"))
    if not (is_streamer or is_pro):
        return None
    name_tag = row.find("span", class_="common_search")
    display_name = name_tag.text.strip() if name_tag and name_tag.text.strip() else None
    if not display_name and link:
        display_name = link.text.strip() or None
    return {
        "label": "STRM" if is_streamer else "PRO",
        "display_name": display_name,
    }


def _store_badge(badge_map: dict, pid: str, badge: dict) -> bool:
    key = normalize_riot_id_key(pid)
    if key in badge_map or pid in badge_map:
        return False
    badge_map[pid] = badge
    badge_map[key] = badge
    return True


def fetch_deeplol_badge_map(deeplol_url: str) -> dict[str, dict]:
    """딥롤 매치 URL에서 STRM/PRO 표시명 수집 (Riot ID → 뱃지 정보)."""
    url = deeplol_url.strip()
    print(f"🖼️ [로딩창] STRM/PRO 조회: {url}")
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=options)
    badge_map: dict[str, dict] = {}
    badge_count = 0

    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "team"))
        )
        time.sleep(1.5)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        for team in soup.find_all("div", class_="team")[:2]:
            before = badge_count
            # 신규 UI: 플레이어 행 class(sc-iaRkIM) 제거됨 → 링크 기준 행 탐색
            for link in team.find_all("a", href=lambda h: h and "/summoner/" in h.lower()):
                pid = parse_riot_id_from_href(link.get("href"))
                if not pid:
                    continue
                row = _find_player_row(link, team)
                badge = _extract_badge_from_row(row, link)
                if badge and _store_badge(badge_map, pid, badge):
                    badge_count += 1

            # 구 UI 폴백 (팀별)
            if badge_count == before:
                for player in team.find_all("div", class_=lambda x: x and x.startswith("sc-iaRkIM")):
                    link = player.find("a", href=lambda h: h and "/summoner/" in h.lower())
                    pid = parse_riot_id_from_href(link.get("href")) if link else None
                    if not pid:
                        continue
                    badge = _extract_badge_from_row(player, link)
                    if badge and _store_badge(badge_map, pid, badge):
                        badge_count += 1
    except Exception as e:
        print(f"⚠️ [로딩창] STRM/PRO 조회 실패: {e}")
    finally:
        driver.quit()

    if badge_count:
        print(f"  ✓ STRM/PRO {badge_count}명 발견")
    else:
        print("  ⚠ STRM/PRO 뱃지 없음 (해당 경기에 뱃지 없음)")

    return badge_map


def resolve_deeplol_url(deeplol_url: str | None = None, deeplol_riot_id: str | None = None, game_id=None) -> str | None:
    if deeplol_url:
        return deeplol_url.strip()
    if deeplol_riot_id and game_id is not None:
        return build_deeplol_match_url(deeplol_riot_id, game_id)
    return None


def get_players_from_match_info(
    match_info: dict,
    deeplol_url: str | None = None,
    deeplol_riot_id: str | None = None,
    game_id=None,
) -> list:
    """Riot 매치 API 참가자 순서(로딩창 포지션)로 10명 정보 구성."""
    participants = match_info.get("participants") or []
    if len(participants) < 10:
        print("⚠️ [로딩창] 참가자 수가 10명 미만입니다.")
        return []

    badge_url = resolve_deeplol_url(deeplol_url, deeplol_riot_id, game_id)
    badge_map = fetch_deeplol_badge_map(badge_url) if badge_url else {}

    players_info = []
    for team_name, team_id in (("블루팀", BLUE_TEAM_ID), ("레드팀", RED_TEAM_ID)):
        for idx, participant in enumerate(_team_participants_for_loading(participants, team_id), start=1):
            position = f"{team_name} {idx}번"
            riot_id = riot_id_from_participant(participant)
            tier_display = fetch_tier_display_by_puuid(participant["puuid"]) if participant.get("puuid") else None
            badge = lookup_badge(badge_map, riot_id)

            players_info.append({
                "position": position,
                "riot_id": riot_id,
                "tier": tier_display,
                "label": badge.get("label"),
                "display_name": badge.get("display_name"),
            })
            time.sleep(0.2)

    return players_info


def get_players_from_game_id(game_id, deeplol_url: str | None = None, deeplol_riot_id: str | None = None) -> list:
    match_id = normalize_match_id(game_id)
    print(f"🖼️ [로딩창] 매치 API 조회: {match_id}")
    match_data = get_match_by_gameId(match_id)
    return get_players_from_match_info(
        match_data["info"],
        deeplol_url=deeplol_url,
        deeplol_riot_id=deeplol_riot_id,
        game_id=game_id,
    )


def get_player_data_from_url(url: str, deeplol_riot_id: str | None = None) -> list:
    match_id = parse_match_id_from_deeplol_url(url)
    if not match_id:
        print("⚠️ URL에서 match ID(KR_...)를 찾지 못했습니다.")
        return []
    match_data = get_match_by_gameId(match_id)
    return get_players_from_match_info(
        match_data["info"],
        deeplol_url=url,
        deeplol_riot_id=deeplol_riot_id,
        game_id=match_id,
    )


def create_overlay_image(players_info, output_path=None, save_dir=r"C:\Users\seok\Downloads"):
    if output_path:
        output_filename = output_path
        save_folder = os.path.dirname(output_path)
        if save_folder and not os.path.exists(save_folder):
            os.makedirs(save_folder)
    else:
        base_name = "overlay"
        ext = ".png"
        counter = 1
        output_filename = os.path.join(save_dir, f"{base_name}_{counter}{ext}")
        while os.path.exists(output_filename):
            counter += 1
            output_filename = os.path.join(save_dir, f"{base_name}_{counter}{ext}")

    img = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    goorm_path = os.path.join(PROJECT_ROOT, "font", "goorm-sans-bold.ttf")
    font_tier = _load_truetype(44, "malgunbd.ttf", r"C:\Windows\Fonts\malgunbd.ttf")
    font_label = _load_truetype(50, "malgunbd.ttf", r"C:\Windows\Fonts\malgunbd.ttf")
    font_name = _load_truetype(50, goorm_path, "malgunbd.ttf", r"C:\Windows\Fonts\malgunbd.ttf")
    font_attribution = _load_truetype(36, "malgun.ttf", r"C:\Windows\Fonts\malgun.ttf")
    font_tier_cjk = _load_cjk_font(44)
    font_label_cjk = _load_cjk_font(50)
    font_name_cjk = _load_cjk_font(50)

    for player in players_info:
        pos_key = player["position"]
        if pos_key not in COORDINATES:
            continue

        x, y = COORDINATES[pos_key]
        tier_text = player.get("tier")
        has_badge = player.get("label") and player.get("display_name")

        if tier_text:
            draw_text_mixed_center(
                draw, (x, y + TIER_Y_OFFSET), tier_text,
                font_tier, font_tier_cjk,
                fill=tier_text_color(tier_text),
                stroke_width=2, stroke_fill="black",
            )

        if has_badge:
            draw_text_mixed_center(
                draw, (x, y + BADGE_Y_OFFSET), player["label"],
                font_label, font_label_cjk,
                fill=badge_text_color(player["label"]),
                stroke_width=3, stroke_fill="black",
            )
            draw_text_mixed_center(
                draw, (x, y + NAME_Y_OFFSET), player["display_name"],
                font_name, font_name_cjk,
                fill=COLOR_NAME,
                stroke_width=2, stroke_fill="black",
            )

    draw.text(
        ATTRIBUTION_POS, ATTRIBUTION_TEXT, font=font_attribution,
        fill=COLOR_ATTRIBUTION,
        anchor="mm", stroke_width=2, stroke_fill="black",
    )

    img.save(output_filename)
    print(f"\n✨ 로딩창 오버레이 저장: {output_filename}")
    return output_filename


def save_loading_overlay(game_id, output_path, deeplol_url=None, deeplol_riot_id=None, match_info=None):
    """
    game_id/match_info 로 10명 Riot ID·티어 조회 후 PNG 저장.
    STRM/PRO 는 deeplol_url (또는 deeplol_riot_id+game_id) 로 딥롤에서 추가 조회.
    """
    if match_info:
        players_info = get_players_from_match_info(
            match_info,
            deeplol_url=deeplol_url,
            deeplol_riot_id=deeplol_riot_id,
            game_id=game_id,
        )
    else:
        players_info = get_players_from_game_id(
            game_id,
            deeplol_url=deeplol_url,
            deeplol_riot_id=deeplol_riot_id,
        )

    if not players_info:
        print("⚠️ [로딩창] 플레이어 정보를 찾지 못했습니다.")
        return None
    return create_overlay_image(players_info, output_path=output_path)


if __name__ == "__main__":
    target = input("딥롤 URL 또는 KR 매치 ID (예: KR_8240707596): ").strip()
    is_match_id = target.upper().startswith("KR_") or target.isdigit()
    deeplol_riot_id = None
    if is_match_id:
        deeplol_riot_id = input("STRM/PRO 조회용 Riot ID (딥롤 URL 없을 때, Enter=건너뜀): ").strip() or None
        found_players = get_players_from_game_id(target, deeplol_riot_id=deeplol_riot_id)
    else:
        found_players = get_player_data_from_url(target)

    if found_players:
        print("\n[추출된 정보]")
        for p in found_players:
            if p.get("label"):
                name = p.get("display_name") or "(표시명 없음)"
                extra = f" | [{p['label']}] {name}"
            else:
                extra = ""
            print(f"- {p['position']} : {p['tier'] or '(티어 없음)'} ({p['riot_id']}){extra}")
        create_overlay_image(found_players)
    else:
        print("플레이어 정보를 찾지 못했습니다.")
