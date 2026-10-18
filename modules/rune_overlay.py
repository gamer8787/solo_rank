"""내 룬 오버레이 PNG 생성 (합성은 modules.loading_intro 에서 함께 처리)."""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from get_image import get_rune_image, get_stat_rune_image, load_rune_data

TREE_NAME_KO = {
    8000: "정밀",
    8100: "지배",
    8200: "마법",
    8300: "영감",
    8400: "결의",
}

# offense / flex / defense 각 행 옵션 (최근 시즌 기준)
STAT_ROWS = (
    (5008, 5005, 5007),
    (5008, 5010, 5011),
    (5011, 5013, 5001),
)

PANEL_BG = (38, 38, 38, 230)
TITLE_COLOR = (230, 230, 230, 255)
INACTIVE_OPACITY = 0.28


def extract_runes_from_participant(participant: dict) -> dict:
    perks = participant["perks"]
    primary = perks["styles"][0]
    secondary = perks["styles"][1]
    return {
        "primary_style": primary["style"],
        "primary_runes": [s["perk"] for s in primary["selections"]],
        "secondary_style": secondary["style"],
        "secondary_runes": [s["perk"] for s in secondary["selections"]],
        "stat_runes": [
            perks["statPerks"]["offense"],
            perks["statPerks"]["flex"],
            perks["statPerks"]["defense"],
        ],
    }


def _load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "font", "goorm-sans-bold.ttf"),
        r"C:\Windows\Fonts\malgunbd.ttf",
        r"C:\Windows\Fonts\malgun.ttf",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _to_rgba(img: Image.Image) -> Image.Image:
    return img.convert("RGBA") if img.mode != "RGBA" else img.copy()


def _resize_square(img: Image.Image, size: int) -> Image.Image:
    return _to_rgba(img).resize((size, size), Image.Resampling.LANCZOS)


def _dim(img: Image.Image, opacity: float = INACTIVE_OPACITY) -> Image.Image:
    gray = ImageEnhance.Color(img).enhance(0.0)
    out = gray.copy()
    alpha = out.split()[-1].point(lambda a: int(a * opacity))
    out.putalpha(alpha)
    return out


def _paste(base: Image.Image, icon: Image.Image, cx: int, cy: int, active: bool) -> None:
    im = icon if active else _dim(icon)
    x = int(cx - im.width / 2)
    y = int(cy - im.height / 2)
    base.alpha_composite(im, (x, y))


def _tree_by_id(style_id: int) -> dict:
    for tree in load_rune_data():
        if tree["id"] == style_id:
            return tree
    raise KeyError(f"Rune style {style_id} not found")


def _rounded_panel(size: tuple[int, int], radius: int = 24, fill=PANEL_BG) -> Image.Image:
    w, h = size
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=fill)
    return panel


def create_rune_overlay_image(rune_info: dict, output_path: str, canvas_size=(1920, 1080)) -> str:
    """딥롤 룬 패널 스타일로 1920x1080 투명 PNG 생성."""
    primary_style = int(rune_info["primary_style"])
    secondary_style = int(rune_info["secondary_style"])
    primary_selected = {int(x) for x in rune_info["primary_runes"]}
    secondary_selected = {int(x) for x in rune_info["secondary_runes"]}
    stats = [int(x) for x in rune_info["stat_runes"]]

    primary_tree = _tree_by_id(primary_style)
    secondary_tree = _tree_by_id(secondary_style)

    W, H = canvas_size
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    panel_w, panel_h = 980, 520
    px = (W - panel_w) // 2
    py = (H - panel_h) // 2
    panel = _rounded_panel((panel_w, panel_h))
    draw = ImageDraw.Draw(panel)
    font_title = _load_font(42)
    font_sub = _load_font(28)

    draw.text((36, 24), "룬", font=font_title, fill=TITLE_COLOR)

    # 열 레이아웃: 주룬 | 보조룬 | 파편
    col_primary_x = 220
    col_secondary_x = 560
    col_stat_x = 850
    top_y = 100

    # --- Primary ---
    p_name = TREE_NAME_KO.get(primary_style, primary_tree.get("name", ""))
    draw.text((col_primary_x, 70), p_name, font=font_sub, fill=TITLE_COLOR, anchor="mm")
    try:
        style_icon = _resize_square(get_rune_image(primary_style), 40)
        _paste(panel, style_icon, col_primary_x - 70, 70, True)
    except Exception:
        pass

    keystone_size = 92
    rune_size = 64
    for slot_idx, slot in enumerate(primary_tree["slots"]):
        runes = slot["runes"]
        n = len(runes)
        y = top_y + (0 if slot_idx == 0 else 110 + (slot_idx - 1) * 88)
        size = keystone_size if slot_idx == 0 else rune_size
        gap = 100 if slot_idx == 0 else 78
        total_w = (n - 1) * gap
        start_x = col_primary_x - total_w / 2
        for i, rune in enumerate(runes):
            rid = rune["id"]
            icon = _resize_square(get_rune_image(rid), size)
            _paste(panel, icon, int(start_x + i * gap), y + size // 2, rid in primary_selected)

    # --- Secondary (키석 슬롯 제외) ---
    s_name = TREE_NAME_KO.get(secondary_style, secondary_tree.get("name", ""))
    draw.text((col_secondary_x, 70), s_name, font=font_sub, fill=TITLE_COLOR, anchor="mm")
    try:
        style_icon = _resize_square(get_rune_image(secondary_style), 40)
        _paste(panel, style_icon, col_secondary_x - 70, 70, True)
    except Exception:
        pass

    sec_slots = secondary_tree["slots"][1:]  # skip keystone
    for slot_idx, slot in enumerate(sec_slots):
        runes = slot["runes"]
        n = len(runes)
        y = top_y + 40 + slot_idx * 100
        gap = 78
        total_w = (n - 1) * gap
        start_x = col_secondary_x - total_w / 2
        for i, rune in enumerate(runes):
            rid = rune["id"]
            icon = _resize_square(get_rune_image(rid), rune_size)
            _paste(panel, icon, int(start_x + i * gap), y + rune_size // 2, rid in secondary_selected)

    # --- Stat shards ---
    draw.text((col_stat_x, 70), "파편", font=font_sub, fill=TITLE_COLOR, anchor="mm")
    shard_size = 48
    for row_i, row in enumerate(STAT_ROWS):
        selected = stats[row_i] if row_i < len(stats) else None
        y = top_y + 50 + row_i * 110
        n = len(row)
        gap = 62
        total_w = (n - 1) * gap
        start_x = col_stat_x - total_w / 2
        for i, sid in enumerate(row):
            try:
                icon = _resize_square(get_stat_rune_image(sid), shard_size)
            except Exception:
                continue
            _paste(panel, icon, int(start_x + i * gap), y + shard_size // 2, sid == selected)

    canvas.alpha_composite(panel, (px, py))
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    canvas.save(output_path)
    print(f"[룬] 오버레이 PNG 저장: {output_path}")
    return output_path


def save_rune_overlay_png(participant: dict, output_png: str) -> str | None:
    """내 룬 오버레이 PNG 생성. 실패 시 None."""
    try:
        rune_info = extract_runes_from_participant(participant)
    except Exception as e:
        print(f"[룬] 룬 데이터 추출 실패: {e}")
        return None
    try:
        return create_rune_overlay_image(rune_info, output_png)
    except Exception as e:
        print(f"[룬] 오버레이 PNG 생성 실패: {e}")
        return None
