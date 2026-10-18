import sys
import os
import json
import re
import urllib.request
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QFrame, QStackedWidget, QScrollArea)
from PySide6.QtGui import QPixmap, QCursor
from PySide6.QtCore import Qt, QTimer

# env.py 위치 찾기 (상위 폴더)
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

# 설정 불러오기
try:
    from env import DDRAGON_USER_AGENT, ddragon_versioned_cdn_root, get_data_dragon_version, TARGET_MONITOR_INDEX
except ImportError:
    DDRAGON_USER_AGENT = "Mozilla/5.0"
    ddragon_versioned_cdn_root = lambda: "https://ddragon.leagueoflegends.com/cdn/16.1.1"
    get_data_dragon_version = lambda: "16.1.1"
    TARGET_MONITOR_INDEX = 1

SCALE = 5 / 6


def _px(n: float) -> int:
    return max(1, round(n * SCALE))


ICON_SIZE = _px(44)
ROW_MIN_HEIGHT = _px(85)
CARD_W, CARD_H = _px(280), _px(520) + 5 * _px(14)
WINDOW_W, WINDOW_H = _px(1500), _px(1100) + 10 * _px(14)

COOLDOWN_FONT_STYLE = (
    f"color: #FF6347; font-size: {_px(18)}px; font-weight: bold; "
    "background: transparent; border: none;"
)
MANA_FONT_STYLE = (
    f"color: #5B9BD5; font-size: {_px(16)}px; font-weight: bold; "
    "background: transparent; border: none;"
)
TITLE_FONT_STYLE = (
    f"color: #FFD700; font-size: {_px(16)}px; font-weight: bold; "
    "background: transparent; border: none;"
)
DESC_FONT_STYLE = (
    f"color: #DDDDDD; font-size: {_px(14)}px; font-weight: normal; "
    "background: transparent; border: none;"
)


def _fmt_num(value) -> str:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(x - round(x)) < 1e-6:
        return str(int(round(x)))
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _fmt_seq(values) -> str:
    if not values:
        return ""
    return "/".join(_fmt_num(v) for v in values)


def _cooldown_text(spell: dict) -> str:
    formatted = _fmt_seq(spell.get("cooldown") or [])
    if not formatted:
        burn = (spell.get("cooldownBurn") or "").strip()
        formatted = burn
    return f"쿨: {formatted}s" if formatted else ""


def _mana_text(spell: dict) -> str:
    costs = spell.get("cost") or []
    formatted = _fmt_seq(costs)
    if not formatted:
        formatted = (spell.get("costBurn") or "").replace(" ", "").strip()
    cost_type = str(spell.get("costType") or "").lower()
    zeros = formatted.replace("/", "")
    no_cost = (
        not formatted
        or set(zeros) <= {"0"}
        or "no cost" in cost_type
        or "소모값 없음" in cost_type
    )
    if no_cost:
        return "마나: 없음"
    if "energy" in cost_type or "기력" in cost_type:
        label = "기력"
    elif "health" in cost_type or "체력" in cost_type:
        label = "체력"
    else:
        label = "마나"
    return f"{label}: {formatted}"


def _pixmap_from_path_or_url(path_or_url: str, w: int, h: int) -> QPixmap:
    if not path_or_url:
        return QPixmap()
    try:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            req = urllib.request.Request(path_or_url, headers={"User-Agent": DDRAGON_USER_AGENT})
            raw = urllib.request.urlopen(req, timeout=25).read()
            pix = QPixmap()
            if not pix.loadFromData(raw):
                return QPixmap()
        else:
            pix = QPixmap(path_or_url)
        return pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception:
        return QPixmap()


class SkillRow(QWidget):
    """스킬 1줄 위젯 (이미지+텍스트+설명)"""

    def __init__(self):
        super().__init__()
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMinimumHeight(ROW_MIN_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_px(10))
        layout.setAlignment(Qt.AlignTop)

        self.img_lbl = QLabel()
        self.img_lbl.setFixedSize(ICON_SIZE, ICON_SIZE)
        self.img_lbl.setStyleSheet("border: 1px solid #555; background-color: #000;")
        layout.addWidget(self.img_lbl)

        self.text_stack = QStackedWidget()
        layout.addWidget(self.text_stack)

        # 1. 기본 정보 (쿨타임 + 마나)
        self.info_widget = QWidget()
        info_lay = QVBoxLayout(self.info_widget)
        info_lay.setContentsMargins(0, _px(5), 0, 0)
        info_lay.setSpacing(_px(2))
        self.title_lbl = QLabel("-")
        self.title_lbl.setStyleSheet(TITLE_FONT_STYLE)
        self.cd_lbl = QLabel("-")
        self.cd_lbl.setStyleSheet(COOLDOWN_FONT_STYLE)
        self.mana_lbl = QLabel("")
        self.mana_lbl.setStyleSheet(MANA_FONT_STYLE)
        info_lay.addWidget(self.title_lbl)
        info_lay.addWidget(self.cd_lbl)
        info_lay.addWidget(self.mana_lbl)
        self.text_stack.addWidget(self.info_widget)

        # 2. 설명창 (스크롤)
        self.desc_scroll = QScrollArea()
        self.desc_scroll.setWidgetResizable(True)
        self.desc_scroll.setStyleSheet("background: transparent; border: none;")
        self.desc_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.desc_lbl = QLabel("설명 없음")
        self.desc_lbl.setStyleSheet(DESC_FONT_STYLE)
        self.desc_lbl.setWordWrap(True)
        self.desc_scroll.setWidget(self.desc_lbl)
        self.text_stack.addWidget(self.desc_scroll)

        self.current_mode = 0

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.current_mode = 1 if self.current_mode == 0 else 0
            self.text_stack.setCurrentIndex(self.current_mode)

    def update_data(self, img_path, key, name, cd_text, desc, mana_text=""):
        pix = _pixmap_from_path_or_url(img_path, ICON_SIZE, ICON_SIZE)
        if not pix.isNull():
            self.img_lbl.setPixmap(pix)
        else:
            self.img_lbl.clear()
            self.img_lbl.setText(key)
        self.title_lbl.setText(f"[{key}] {name}")
        self.cd_lbl.setText(cd_text)
        self.cd_lbl.setVisible(bool(cd_text))
        self.mana_lbl.setText(mana_text)
        self.mana_lbl.setVisible(bool(mana_text))
        self.desc_lbl.setText(re.sub('<.*?>', '', desc))  # HTML 태그 제거


class ChampionCard(QFrame):
    """챔피언 1명의 카드"""

    def __init__(self, team_color):
        super().__init__()
        self.setFrameShape(QFrame.Box)
        self.setFixedSize(CARD_W, CARD_H)
        border = "#00BFFF" if team_color == "blue" else "#FF4500"
        self.setStyleSheet(
            f"ChampionCard {{ background-color: #252525; border: {_px(2)}px solid {border}; border-radius: {_px(12)}px; }} QLabel {{ border: none; background: transparent; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_px(10), _px(10), _px(10), _px(10))
        layout.setSpacing(_px(2))

        self.name_label = QLabel("Waiting...")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setStyleSheet(
            f"color: white; font-weight: bold; font-size: {_px(20)}px; border: none; margin-bottom: {_px(5)}px;")
        layout.addWidget(self.name_label)

        self.skill_rows = [SkillRow() for _ in range(5)]
        for r in self.skill_rows: layout.addWidget(r)
        layout.addStretch(1)

    def update_info(self, detail, s_name):
        c_name = detail.get('name', 'Unknown')
        display_name = f"{c_name}\n({s_name})" if s_name and s_name.strip() else f"{c_name}"
        self.name_label.setText(display_name)

        root = ddragon_versioned_cdn_root()
        p = detail.get('passive', {})
        pfile = p.get('image', {}).get('full', '')
        purl = f"{root}/img/passive/{pfile}" if pfile else ""
        self.skill_rows[0].update_data(
            purl, "P", p.get('name', '패시브'), "", p.get('description', ''), ""
        )

        spells = detail.get('spells', [])
        keys = ["Q", "W", "E", "R"]
        for i, key in enumerate(keys):
            if i < len(spells):
                s = spells[i]
                sfile = s.get('image', {}).get('full', '')
                surl = f"{root}/img/spell/{sfile}" if sfile else ""
                self.skill_rows[i + 1].update_data(
                    surl, key, s.get('name', ''),
                    _cooldown_text(s), s.get('description', ''), _mana_text(s),
                )
            else:
                self.skill_rows[i + 1].update_data("", key, "-", "", "", "")

    def reset_card(self):
        self.name_label.setText("Waiting...")
        for r in self.skill_rows: r.update_data("", "-", "-", "", "", "")


class SkillWindow(QWidget):
    def __init__(self, pipe_conn):
        super().__init__()
        self.pipe_conn = pipe_conn
        self.setGeometry(0, 0, WINDOW_W, WINDOW_H)
        self.setStyleSheet("background-color: #121212;")
        self.champs_map = self.load_all_champs()
        self._detail_cache = {}
        self._ddragon_ver = get_data_dragon_version()

        layout = QVBoxLayout(self)
        self.blue_layout = QHBoxLayout()
        self.red_layout = QHBoxLayout()

        layout.addLayout(self.blue_layout)
        line = QFrame();
        line.setFrameShape(QFrame.HLine);
        line.setStyleSheet(f"background: #444; margin: {_px(15)}px 0;")
        layout.addWidget(line)
        layout.addLayout(self.red_layout)

        self.blue_cards = [ChampionCard("blue") for _ in range(5)]
        self.red_cards = [ChampionCard("red") for _ in range(5)]
        for c in self.blue_cards: self.blue_layout.addWidget(c)
        for c in self.red_cards: self.red_layout.addWidget(c)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_pipe)
        self.timer.start(500)  # 0.5초마다 데이터 확인

    def load_all_champs(self):
        mapping = {}
        try:
            url = f"{ddragon_versioned_cdn_root()}/data/ko_KR/champion.json"
            req = urllib.request.Request(url, headers={"User-Agent": DDRAGON_USER_AGENT})
            with urllib.request.urlopen(req, timeout=25) as resp:
                blob = json.loads(resp.read().decode("utf-8"))
            for v in blob["data"].values():
                mapping[int(v["key"])] = v["id"]
        except Exception:
            pass
        return mapping

    def check_pipe(self):
        if self.pipe_conn and self.pipe_conn.poll():
            try:
                data = self.pipe_conn.recv()
                self.update_ui(data.get('team_one', []), data.get('team_two', []))
            except:
                pass

    def update_ui(self, t1, t2):
        v = get_data_dragon_version()
        if v != self._ddragon_ver:
            self._ddragon_ver = v
            self._detail_cache.clear()
            self.champs_map = self.load_all_champs()

        for i, c in enumerate(self.blue_cards):
            if i < len(t1) and t1[i]['championId'] > 0:
                detail = self.get_detail(t1[i]['championId'])
                if detail: c.update_info(detail, t1[i]['summonerName'])
            else:
                c.reset_card()

        for i, c in enumerate(self.red_cards):
            if i < len(t2) and t2[i]['championId'] > 0:
                detail = self.get_detail(t2[i]['championId'])
                if detail: c.update_info(detail, t2[i]['summonerName'])
            else:
                c.reset_card()

    def get_detail(self, c_id):
        eng_id = self.champs_map.get(c_id)
        if not eng_id:
            return None
        if eng_id in self._detail_cache:
            return self._detail_cache[eng_id]
        try:
            url = f"{ddragon_versioned_cdn_root()}/data/ko_KR/champion/{eng_id}.json"
            req = urllib.request.Request(url, headers={"User-Agent": DDRAGON_USER_AGENT})
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            detail = data["data"][eng_id]
            self._detail_cache[eng_id] = detail
            return detail
        except Exception:
            return None


def show_overlay(connector, team_one, team_two, pipe_conn):
    app = QApplication.instance() or QApplication(sys.argv)
    win = SkillWindow(pipe_conn)
    win.show()

    # 모니터 이동 로직
    screens = QApplication.screens()
    idx = TARGET_MONITOR_INDEX if TARGET_MONITOR_INDEX < len(screens) else 0

    target_screen = screens[idx]
    geo = win.frameGeometry()
    geo.moveCenter(target_screen.geometry().center())
    win.move(geo.topLeft())

    app.exec()