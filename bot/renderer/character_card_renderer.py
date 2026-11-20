"""The "Teyvat Build Card" — the character showcase card (1536x864 PNG).

Drawn entirely in code; there is no baked template to paint over. The design was ported
from the approved *Teyvat Build Card Studio* reference (a light, editorial three-column
layout with an element-tinted palette: parchment art panel | warm ivory identity column |
near-black artifacts rail):

    +----------------+----------------------+-------------------+
    |  region chip   | kicker               | EQUIPPED · 5      |
    |  splash art    | NAME          ★★★★★  |        TOTAL  CV  |
    |                | epithet              | Artifacts     (C) |
    |                +----------------------+                   |
    |  ┌──────────┐  | LEVEL|CONST.|FRIEND.| flower · +20 …    |
    |  │CONSTEL-  │  ├──────────────────────┤ …                 |
    |  │ LATION   |  |  WEAPON (dark box)   |                   |
    |  │  C1‥C6   |  ├──────────────────────┤                   |
    |  └──────────┘  | ■ ATTRIBUTES         |───────────────────|
    |                |   radar   rows       | Set name     4-PC |
    |                | ■ TALENTS            | 2-PC / 4-PC text  |
    |     UID …      |       TEYVAT BUILD   |                   |
    +----------------+----------------------+-------------------+

Element theming recolours the whole card (accent, panels, gradients) from ``data.character``;
nothing about the layout itself changes. Strings Enka does not report (kicker affiliation,
epithet, constellation name, weapon passive, set effects) come from the bundled tables in
``bot/resources/*.json`` via :mod:`bot.renderer.flavor`; anything missing is simply not
drawn — the card never invents game text.

CRIT Value per artifact (and the artefact header total) is ``2 x CRIT Rate + CRIT DMG``
summed over *substats only* (a CRIT circlet's main stat does not count), which is the same
convention the reference studio used. Stat-row emphasis follows a deterministic rule
(:func:`_emphasised_rows`) that reproduces the reference cards exactly.

Every position below is a constant of this design; a new character needs only data.
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from bot.renderer import image_fitter
from bot.renderer.card_data import CardData
from bot.renderer.card_layout import canonical_element
from bot.renderer.image_fitter import Adjustment
from bot.utils.logging import get_logger

logger = get_logger(__name__)

WIDTH, HEIGHT = 1536, 864
LEFT_W = 511                    # art panel:      0 .. 511
MID_L, MID_R = 533, 988         # middle content: 533..988 (panel 511..1010)
RIGHT_L, RIGHT_R = 1044, 1502   # right content:  1044..1502 (panel 1010..1536)
ICONS_DIR = Path(__file__).resolve().parent / "icons"

# Palette: warm ivory centre, near-black rails, warm greys for captions.
IVORY_TOP = (248, 243, 230)
IVORY_BOTTOM = (240, 234, 219)
INK = (27, 23, 18)              # names / values on ivory
INK_2 = (92, 86, 75)            # secondary text on ivory
INK_3 = (138, 131, 117)         # captions on ivory
HAIRLINE = (36, 31, 22, 34)     # hairline on ivory
DOT = (178, 170, 153)           # dotted leader dots on ivory
PAPER_PANEL = (247, 242, 230)   # constellation overlay
DARK_TEXT = (245, 241, 230)     # primary text on the dark rail
DARK_MUTED = (167, 156, 140)    # captions on the dark rail
DARK_FAINT = (137, 128, 115)    # fainter captions on the dark rail
DARK_LINE = (255, 255, 255, 15)

_ELEMENT_ICONS = {
    "PYRO": "pyro", "HYDRO": "hydro", "ELECTRO": "electro", "CRYO": "cryo",
    "ANEMO": "anemo", "GEO": "geo", "DENDRO": "dendro",
}
_SLOTS = ("flower", "plume", "sands", "goblet", "circlet")
_TALENT_LABELS = (("normal", "NORMAL"), ("skill", "SKILL"), ("burst", "BURST"))

# Substat single-roll maxima (5-star, no set) — used to scale the micro bars.
_SUBSTAT_CAP = {
    "crit rate": 31.1, "crit dmg": 62.2,
    "hp": 4780.0, "atk": 311.0, "def": 233.0,
    "hp%": 46.6, "atk%": 46.6, "def%": 46.6,
    "energy recharge": 51.8, "elemental mastery": 187.0,
}
# Radar axis normalisation maxima.
_RADAR_MAX = {"scaling": 1.0, "crit rate": 100.0, "crit dmg": 250.0,
              "er": 250.0, "em": 300.0, "dmg": 80.0}

# Artifact CV grade thresholds (total of substat CRIT value across the 5 pieces).
_CV_GRADES = (("SS", 210.0), ("S", 185.0), ("A", 175.0), ("B", 155.0), ("C", 110.0), ("D", 0.0))


@dataclass(frozen=True)
class _Theme:
    accent: tuple        # vivid element colour — chips, fills, bars on dark
    accent_ink: tuple    # deep element colour — emphasis text on ivory
    left_top: tuple      # art panel gradient (top)
    left_bottom: tuple   # art panel gradient (bottom)
    right_top: tuple     # artifacts rail gradient (top)
    right_bottom: tuple  # artifacts rail gradient (bottom)
    weapon_box: tuple    # dark weapon panel
    weapon_icon: tuple   # icon tile inside the weapon panel


_THEMES: dict[str, _Theme] = {
    "PYRO": _Theme((236, 84, 54), (199, 62, 34), (251, 231, 216), (244, 210, 189),
                   (38, 18, 16), (26, 11, 11), (40, 20, 18), (49, 25, 23)),
    "HYDRO": _Theme((62, 134, 216), (46, 95, 146), (231, 238, 246), (210, 225, 238),
                    (16, 26, 42), (10, 17, 30), (19, 30, 48), (24, 36, 55)),
    "ELECTRO": _Theme((154, 111, 224), (111, 77, 180), (237, 233, 247), (220, 210, 236),
                      (26, 20, 40), (17, 13, 30), (30, 23, 51), (36, 27, 58)),
    "GEO": _Theme((200, 154, 59), (143, 106, 32), (247, 233, 205), (238, 219, 170),
                  (34, 26, 16), (22, 17, 10), (38, 29, 18), (46, 36, 23)),
    "CRYO": _Theme((87, 183, 217), (47, 122, 153), (233, 244, 247), (210, 230, 236),
                   (15, 32, 40), (10, 22, 28), (20, 40, 50), (26, 48, 58)),
    "ANEMO": _Theme((62, 198, 164), (31, 138, 110), (230, 245, 238), (205, 232, 221),
                    (13, 37, 30), (9, 26, 21), (18, 46, 38), (24, 55, 45)),
    "DENDRO": _Theme((111, 201, 78), (62, 138, 42), (236, 246, 224), (216, 232, 196),
                     (18, 37, 15), (12, 26, 10), (26, 46, 22), (33, 55, 28)),
}
_DEFAULT_THEME = _Theme((176, 165, 142), (110, 103, 92), (247, 243, 232), (233, 228, 216),
                        (30, 30, 33), (21, 21, 24), (38, 38, 42), (46, 46, 51))


def theme_for_element(element: str | None) -> _Theme:
    canon = canonical_element(element)
    return _THEMES.get(canon or "", _DEFAULT_THEME)


class CharacterCardRenderer:
    """Renders a :class:`CardData` to the showcase PNG."""

    def __init__(self, font_provider=None) -> None:
        self._font_for = font_provider or _provider()

    # -- public API --------------------------------------------------------
    def render(self, data: CardData, *, debug: bool = False) -> bytes:
        """Render ``data`` to PNG bytes at 1536x864."""
        theme = theme_for_element(data.character.element)
        base = _canvas_base(theme).copy()

        self._draw_hero(base, data, theme)
        draw = ImageDraw.Draw(base, "RGBA")
        self._draw_identity(base, draw, data, theme)
        self._draw_level_row(draw, data)
        self._draw_weapon(base, draw, data, theme)
        self._draw_attributes(base, draw, data, theme)
        self._draw_talents(base, draw, data, theme)
        self._draw_footer(draw, data)
        self._draw_artifacts(base, draw, data, theme)
        self._draw_set_bonus(draw, data, theme)
        if debug:
            self._draw_debug_overlay(draw)

        buf = io.BytesIO()
        base.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()

    # -- text helpers ------------------------------------------------------
    def _font(self, size: int, weight: int = 400, *, serif: bool = False):
        return self._font_for(size, weight, serif=serif)

    def _text(self, draw, xy, text, font, fill, *, anchor="lm", tracking=0.0) -> float:
        """Draw ``text``; returns its advance width. ``tracking`` adds per-letter spacing."""
        if not text:
            return 0.0
        if not tracking:
            draw.text(xy, text, font=font, fill=fill, anchor=anchor)
            return font.getlength(text)
        width = sum(font.getlength(ch) for ch in text) + tracking * (len(text) - 1)
        x, y = xy
        if anchor[0] == "r":
            x -= width
        elif anchor[0] == "m":
            x -= width / 2
        for ch in text:
            draw.text((x, y), ch, font=font, fill=fill, anchor="l" + anchor[1])
            x += font.getlength(ch) + tracking
        return width

    def _tracked_width(self, text: str, font, tracking: float) -> float:
        return sum(font.getlength(ch) for ch in text) + tracking * (len(text) - 1 if text else 0)

    @staticmethod
    def _ellipsize(text: str, font, max_width: float) -> str:
        if font.getlength(text) <= max_width:
            return text
        while text and font.getlength(text + "…") > max_width:
            text = text[:-1]
        return text.rstrip() + "…"

    @classmethod
    def _wrap(cls, text: str, font, max_width: float, max_lines: int) -> list[str]:
        """Greedy word wrap; the last allowed line is ellipsized if text remains."""
        lines: list[str] = []
        words = text.split()
        while words and len(lines) < max_lines:
            line = words.pop(0)
            while words and font.getlength(f"{line} {words[0]}") <= max_width:
                line = f"{line} {words.pop(0)}"
            lines.append(line)
        if words:
            lines[-1] = cls._ellipsize(f"{lines[-1]} {' '.join(words)}", font, max_width)
        return [cls._ellipsize(line, font, max_width) for line in lines]

    def _italic(self, base, xy, text, font, fill, *, anchor="lm", shear=0.22) -> float:
        """Fake-italic: render the string to a tile and shear it (Cormorant has no italic axis)."""
        if not text:
            return 0.0
        pad = 8
        w = math.ceil(font.getlength(text)) + pad * 2 + math.ceil(12 * shear)
        h = font.size + pad * 2
        tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((pad, pad), text, font=font, fill=fill)
        sheared = tile.transform((w + math.ceil(h * shear), h), Image.AFFINE,
                                 (1, shear, 0, 0, 1, 0), resample=Image.BICUBIC)
        x, y = xy
        if anchor[0] == "r":
            x -= sheared.width
        elif anchor[0] == "m":
            x -= sheared.width / 2
        if anchor[1] == "m":
            y -= sheared.height / 2
        base.alpha_composite(sheared, (round(x), round(y - sheared.height / 2)))
        return sheared.width

    def _caps(self, draw, xy, text, fill, *, size=11, weight=600, tracking=None, anchor="lm"):
        tracking = size * 0.22 if tracking is None else tracking
        return self._text(draw, xy, text.upper(), self._font(size, weight), fill,
                          anchor=anchor, tracking=tracking)

    # =================================================================
    # LEFT PANEL — splash art, element chip, constellation map
    # =================================================================
    def _draw_hero(self, base, data: CardData, theme: _Theme) -> None:
        ch = data.character
        canon = canonical_element(ch.element)

        # Portrait, full-bleed across the panel (behind the translucent overlay).
        if data.portrait is not None:
            _place_portrait(base, data.portrait, data.character_adjustment)
        else:
            _draw_no_portrait(base)

        # Element chip + region/weapon pill.
        chip = (36, 32, 78, 74)
        draw = ImageDraw.Draw(base, "RGBA")
        draw.rounded_rectangle(chip, 9, fill=(*theme.accent, 255))
        elem_icon = _ELEMENT_ICONS.get(canon or "")
        if elem_icon:
            base.alpha_composite(_icon(elem_icon, 26, (24, 20, 16)),
                                 (chip[0] + 8, chip[1] + 8))
        label_bits = [b for b in ((data.flavor.region if data.flavor else "") or "",
                                  (ch.weapon_type or "").upper()) if b]
        pill_text = "  ·  ".join(part.upper() for part in label_bits)
        if pill_text:
            font = self._font(13, 700)
            track = 2.6
            text_w = self._tracked_width(pill_text, font, track)
            px0, py0 = 90, 34
            px1 = px0 + int(text_w) + 36
            draw.rounded_rectangle((px0, py0, px1, py0 + 40), 6, fill=(23, 19, 16, 238))
            self._text(draw, (px0 + 18, py0 + 21), pill_text, font, (242, 237, 224),
                       anchor="lm", tracking=track)

        self._draw_constellation_panel(base, draw, data, theme)

    def _draw_constellation_panel(self, base, draw, data: CardData, theme: _Theme) -> None:
        const_name = (data.flavor.constellation_name if data.flavor else "") or ""
        unlocked = max(0, min(6, data.character.constellation))
        box = (24, 668, LEFT_W - 24, 842)

        # Soft drop shadow so the translucent panel sits off the artwork.
        shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (box[0] + 2, box[1] + 6, box[2] + 2, box[3] + 6), 10, fill=(15, 12, 8, 110))
        shadow = shadow.filter(ImageFilter.GaussianBlur(9))
        base.alpha_composite(shadow)
        draw.rounded_rectangle(box, 10, fill=(*PAPER_PANEL, 228),
                               outline=(36, 31, 22, 30), width=1)

        x = box[0] + 18
        self._caps(draw, (x, 700), "Constellation", (107, 100, 88), size=11, tracking=2.8)
        if const_name:
            self._italic(base, (box[2] - 18, 700), const_name,
                         self._font(17, 600, serif=True), (42, 36, 28), anchor="rm")

        xs = [box[0] + 42 + i * 72 for i in range(6)]
        offsets = [0, 26, -16, 18, -22, 6]
        ys = [766 + o for o in offsets]

        # Dashed connectors between consecutive nodes.
        for i in range(5):
            _dashed_line(draw, (xs[i], ys[i]), (xs[i + 1], ys[i + 1]),
                         fill=(128, 120, 106, 220), width=2, dash=7, gap=6)

        for i, (cx, cy) in enumerate(zip(xs, ys)):
            if i < unlocked:
                glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
                ImageDraw.Draw(glow).ellipse((cx - 12, cy - 12, cx + 12, cy + 12),
                                             fill=(*theme.accent, 70))
                base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3)))
                draw.ellipse((cx - 6.4, cy - 6.4, cx + 6.4, cy + 6.4),
                             fill=(*theme.accent, 255), outline=(255, 255, 255, 200), width=1)
            else:
                draw.ellipse((cx - 6.4, cy - 6.4, cx + 6.4, cy + 6.4),
                             fill=(*PAPER_PANEL, 255), outline=(138, 131, 117, 255), width=2)
            self._caps(draw, (cx, cy + 22), f"C{i + 1}", (107, 100, 88), size=9,
                       tracking=1.5, anchor="mm")

    # =================================================================
    # MIDDLE PANEL — identity, weapon, attributes, talents, footer
    # =================================================================
    def _draw_identity(self, base, draw, data: CardData, theme: _Theme) -> None:
        ch = data.character
        flavor = data.flavor

        # Kicker: "N° 04 — WANGSHENG FUNERAL PARLOR".
        kicker_y = 47
        x = MID_L
        if flavor and (flavor.fig or flavor.affiliation):
            if flavor.fig:
                x += self._caps(draw, (x, kicker_y), f"N° {flavor.fig}", theme.accent_ink,
                                size=11, tracking=2.2) + 10
            if flavor.fig and flavor.affiliation:
                draw.line((x, kicker_y, x + 30, kicker_y), fill=HAIRLINE, width=1)
                x += 40
            if flavor.affiliation:
                self._caps(draw, (x + 2, kicker_y), flavor.affiliation, (110, 103, 92),
                           size=10, tracking=2.6)

        # Name — big Didone-style serif.
        name = ch.name or ""
        size = 66
        font = self._font(size, 600, serif=True)
        while size > 34 and font.getlength(name) > 452:
            size -= 2
            font = self._font(size, 600, serif=True)
        name = self._ellipsize(name, font, 452)
        draw.text((MID_L - 2, 122), name, font=font, fill=INK, anchor="ls")

        # Epithet — italic serif in the element's deep colour.
        if flavor and flavor.epithet:
            self._italic(base, (MID_L, 152), flavor.epithet, self._font(19, 500, serif=True),
                         theme.accent_ink, anchor="lm")

        # Rarity stars, right aligned on the name row.
        star = _icon("star", 17, theme.accent_ink)
        sx = MID_R
        for _ in range(max(0, min(ch.rarity or 0, 5))):
            sx -= 17
            base.alpha_composite(star, (int(sx), 130))
            sx -= 7

        draw.line((MID_L, 174, MID_R, 174), fill=HAIRLINE, width=1)

    def _draw_level_row(self, draw, data: CardData) -> None:
        ch = data.character
        cells = [
            ("LEVEL", str(ch.level), f"/ {ch.max_level}"),
            ("CONSTELLATION", f"C{ch.constellation}", "of 6"),
            ("FRIENDSHIP", str(ch.friendship) if ch.friendship is not None else "—",
             f"/ {ch.friendship}" if ch.friendship is not None else ""),
        ]
        bounds = [(MID_L, 677), (677, 836), (836, MID_R)]
        value_font = self._font(40, 700, serif=True)
        suffix_font = self._font(14, 500)
        label_font = self._font(10, 600)
        for i, (label, value, suffix) in enumerate(cells):
            x0, x1 = bounds[i]
            cx = x0 + (4 if i == 0 else 20)
            self._text(draw, (cx, 196), label, label_font, INK_3, tracking=2.4)
            vw = self._text(draw, (cx, 244), value, value_font, INK, anchor="ls")
            if suffix:
                self._text(draw, (cx + vw + 6, 245), suffix, suffix_font, INK_3, anchor="ls")
        for div in (677, 836):
            draw.line((div, 188, div, 258), fill=HAIRLINE, width=1)
        draw.line((MID_L, 272, MID_R, 272), fill=HAIRLINE, width=1)

    def _draw_weapon(self, base, draw, data: CardData, theme: _Theme) -> None:
        box = (MID_L, 292, MID_R, 452)
        # Hard element-coloured offset shadow (bottom-right), per the reference.
        draw.rounded_rectangle((box[0] + 7, box[1] + 7, box[2] + 7, box[3] + 7), 11,
                               fill=(*theme.accent, 235))
        draw.rounded_rectangle(box, 11, fill=(*theme.weapon_box, 255))

        icon_box = (box[0] + 18, box[1] + 22, box[0] + 114, box[1] + 118)
        draw.rounded_rectangle(icon_box, 9, fill=(*theme.weapon_icon, 255),
                               outline=(*theme.accent, 92), width=1)
        _paste_glyph_or_icon(base, data.weapon_image if data else None,
                             (icon_box[0] + 8, icon_box[1] + 8, icon_box[2] - 8, icon_box[3] - 8),
                             theme, fallback=data.character.weapon_type if data else "")

        w = data.weapon
        tx = icon_box[2] + 22
        if w is None:
            self._caps(draw, (tx, 336), "Weapon", (167, 156, 140), size=10)
            draw.text((tx, 372), "No weapon equipped", font=self._font(15, 500),
                      fill=(167, 156, 140), anchor="lm")
            return

        wlevel = ""
        if w.level_text:
            # "Lv. 90 / 90" -> "LV.90" for the caption line.
            m = re.match(r"Lv\.?\s*(\d+)", w.level_text)
            wlevel = f"LV.{m.group(1)}" if m else w.level_text.upper()
        caption = "WEAPON" + (f"  ·  {wlevel}" if wlevel else "")
        self._caps(draw, (tx, 322), caption, (167, 156, 140), size=10, tracking=2.0)

        # Refinement chip, top-right of the box.
        if w.refinement_text:
            chip_font = self._font(13, 700)
            cw = int(chip_font.getlength(w.refinement_text)) + 22
            cx1 = box[2] - 16
            draw.rounded_rectangle((cx1 - cw, box[1] + 16, cx1, box[1] + 44), 5,
                                   fill=(*theme.accent, 255))
            self._text(draw, (cx1 - cw / 2, box[1] + 31), w.refinement_text, chip_font,
                       (26, 20, 14), anchor="mm")

        name_size = 27
        name_font = self._font(name_size, 700, serif=True)
        while name_size > 17 and name_font.getlength(w.name or "") > box[2] - tx - 16:
            name_size -= 1
            name_font = self._font(name_size, 700, serif=True)
        name = self._ellipsize(w.name or "", name_font, box[2] - tx - 16)
        draw.text((tx, 360), name, font=name_font, fill=DARK_TEXT, anchor="ls")

        # "ATK 608   ATK% 49.0%" — labels muted, values warm white / accent.
        row_y = 392
        x = tx
        self._caps(draw, (x, row_y), "ATK", (140, 130, 116), size=10, tracking=1.6)
        x += self._tracked_width("ATK", self._font(10, 600), 1.6) + 8
        atk_v = w.base_attack or "--"
        self._text(draw, (x, row_y), atk_v, self._font(15, 700), (240, 233, 218))
        x += self._font(15, 700).getlength(atk_v) + 22
        if w.secondary_stat:
            sec_label = (w.secondary_stat_name or "").strip() or "Substat"
            self._caps(draw, (x, row_y), sec_label, (140, 130, 116), size=10, tracking=1.6)
            x += self._tracked_width(sec_label.upper(), self._font(10, 600), 1.6) + 8
            self._text(draw, (x, row_y), w.secondary_stat, self._font(15, 700),
                       theme.accent)

        # Passive description (from the bundled table; omitted when unknown).
        passive = (data.flavor.weapon_passive if data.flavor else "") or ""
        if passive:
            passive_font = self._font(11, 400)
            for k, line in enumerate(self._wrap(passive, passive_font, box[2] - tx - 16, 2)):
                draw.text((tx, 414 + 17 * k), line, font=passive_font,
                          fill=(156, 146, 130), anchor="lm")

    # =================================================================
    # ATTRIBUTES — radar + dotted-leader rows
    # =================================================================
    def _draw_attributes(self, base, draw, data: CardData, theme: _Theme) -> None:
        hy = 486
        draw.rectangle((MID_L, hy - 4, MID_L + 9, hy + 5), fill=(*theme.accent, 255))
        x_end = self._caps(draw, (MID_L + 18, hy), "Attributes", (107, 100, 88), size=11,
                           tracking=2.6) + MID_L + 28
        draw.line((x_end + 6, hy, MID_R, hy), fill=HAIRLINE, width=1)

        s = data.stats
        hp_v, atk_v = _stat_number(s.hp), _stat_number(s.atk)
        er_v, cr_v, cd_v, em_v = (_stat_number(s.energy_recharge), _stat_number(s.crit_rate),
                                  _stat_number(s.crit_dmg), _stat_number(s.em))
        dmg_v = _stat_number(s.elemental_bonus)
        scaling_is_hp = hp_v >= 40_000

        _draw_radar(base, (608, 585), 47, theme,
                    top=("HP" if scaling_is_hp else "ATK"),
                    values=[
                        min(1.0, (hp_v if scaling_is_hp else atk_v) / (60_000 if scaling_is_hp else 2_800)),
                        min(1.0, cr_v / 100.0),
                        min(1.0, cd_v / 250.0),
                        min(1.0, er_v / 250.0),
                        min(1.0, em_v / 300.0),
                        min(1.0, dmg_v / 80.0),
                    ])

        emphasis = _emphasised_rows(hp_v=hp_v, crit_rate=cr_v, crit_dmg=cd_v,
                                    energy_recharge=er_v)
        rows = (
            ("hp", "Max HP", s.hp),
            ("atk", "ATK", s.atk),
            ("def", "DEF", s.defense),
            ("em", "Elemental Mastery", s.em),
            ("crit_rate", "CRIT Rate", s.crit_rate),
            ("crit_dmg", "CRIT DMG", s.crit_dmg),
            ("er", "Energy Recharge", s.energy_recharge),
            ("dmg", s.elemental_bonus_name or "DMG Bonus", s.elemental_bonus),
        )
        label_font, value_font = self._font(14.5, 500), self._font(15.5, 600)
        y = 514
        pitch = 18.6
        for i, (key, label, value) in enumerate(rows):
            cy = y + i * pitch
            hot = key in emphasis
            if key == "dmg":
                hot = True
            lf = self._font(14.5, 700 if hot else 500)
            vf = self._font(15.5, 700 if hot else 600)
            self._text(draw, (742, cy), label, lf, INK if hot else INK_2)
            vw = vf.getlength(value)
            label_w = lf.getlength(label)
            self._text(draw, (MID_R, cy), value, vf,
                       theme.accent_ink if hot else INK, anchor="rm")
            _dotted_leader(draw, 742 + label_w + 10, MID_R - vw - 10, cy, fill=DOT)

    # =================================================================
    # TALENTS — dashed element rings
    # =================================================================
    def _draw_talents(self, base, draw, data: CardData, theme: _Theme) -> None:
        hy = 676
        draw.rectangle((MID_L, hy - 4, MID_L + 9, hy + 5), fill=(*theme.accent, 255))
        x_end = self._caps(draw, (MID_L + 18, hy), "Talents", (107, 100, 88), size=11,
                           tracking=2.6) + MID_L + 28
        draw.line((x_end + 6, hy, MID_R, hy), fill=HAIRLINE, width=1)

        label_font = self._font(9.5, 600)
        level_font = self._font(12.5, 600)

        for i, (key, label) in enumerate(_TALENT_LABELS):
            cell_left = MID_L + i * 155
            cell_right = MID_R if i == 2 else MID_L + (i + 1) * 155
            cx = cell_left + 33
            cy = 758
            _dashed_circle(draw, cx, cy, 26, fill=(*theme.accent, 255), width=3,
                           dash_deg=22, gap_deg=14)

            talent = data.talents.get(key)
            if talent is not None and talent.image is not None:
                _paste_glyph_or_icon(base, talent.image,
                                     (cx - 16, cy - 16, cx + 16, cy + 16),
                                     theme, on_dark=False)
            else:
                glyph = {"normal": "atk", "skill": "em", "burst": "star"}.get(key, "em")
                base.alpha_composite(_icon(glyph, 20, (36, 31, 22)), (cx - 10, cy - 10))

            tx = cell_left + 68
            max_w = cell_right - tx - 2
            tiny_name = self._font(10, 700)
            self._text(draw, (tx, 726), label, label_font, INK_3, tracking=2.0)
            if talent is not None:
                # Real Enka talent name when available, else the canonical slot label.
                reported = (talent.name or "").strip()
                if reported.lower() in ("normal", "skill", "burst"):
                    reported = ""
                name = reported or {"normal": "Normal Attack", "skill": "Elemental Skill",
                                    "burst": "Elemental Burst"}[key]
                lines = self._wrap(name, tiny_name, max_w, 3)
                ty = 742
                for line in lines:
                    draw.text((tx, ty), line, font=tiny_name, fill=INK, anchor="lm")
                    ty += 13
                self._text(draw, (tx, 800), f"Lv. {talent.level}", level_font,
                           theme.accent_ink, anchor="lm")
            else:
                draw.text((tx, 752), "—", font=tiny_name, fill=INK_3, anchor="lm")

    # =================================================================
    # FOOTER
    # =================================================================
    def _draw_footer(self, draw, data: CardData) -> None:
        y = 840
        if data.player_uid:
            self._caps(draw, (MID_L, y), f"UID {data.player_uid}", (150, 143, 128),
                       size=11, tracking=1.6)
        self._caps(draw, (MID_R, y), "Teyvat Build Card", (163, 154, 137), size=10.5,
                   tracking=2.6, anchor="rm")

    # =================================================================
    # RIGHT PANEL — artifacts
    # =================================================================
    def _draw_artifacts(self, base, draw, data: CardData, theme: _Theme) -> None:
        equipped = sum(1 for s in _SLOTS if data.artifacts.get(s) is not None)
        pieces_label = f"EQUIPPED  ·  {equipped} PIECE{'S' if equipped != 1 else ''}"
        self._caps(draw, (RIGHT_L, 46), pieces_label, DARK_MUTED, size=10.5, tracking=1.8)

        total_cv = artifact_total_cv(data.artifacts)
        grade = artifact_cv_grade(total_cv)

        # Artifacts title (serif, white).
        draw.text((RIGHT_L, 100), "Artifacts", font=self._font(43, 700, serif=True),
                  fill=DARK_TEXT, anchor="ls")

        # Right group: TOTAL CV caption, big value, grade chip.
        self._caps(draw, (1428, 42), "Total CV", DARK_FAINT, size=9.5, tracking=2.0,
                   anchor="rm")
        self._text(draw, (1428, 80), f"{total_cv:.1f}", self._font(39, 700, serif=True),
                   theme.accent, anchor="rm")
        chip = (1440, 34, 1500, 88)
        draw.rounded_rectangle(chip, 8, fill=(*theme.accent, 255))
        self._text(draw, ((chip[0] + chip[2]) / 2, (chip[1] + chip[3]) / 2), grade,
                   self._font(27, 700, serif=True), (30, 23, 15), anchor="mm")

        y0, pitch = 124, 103
        sub_value = self._font(12, 700)
        bar_h = 3

        for i, slot in enumerate(_SLOTS):
            top = y0 + i * pitch
            if i:
                draw.line((RIGHT_L, top - 1, RIGHT_R, top - 1), fill=DARK_LINE, width=1)

            icon_box = (RIGHT_L, top + 8, RIGHT_L + 62, top + 72)
            draw.rounded_rectangle(icon_box, 7, outline=(*theme.accent, 130), width=2)
            _draw_slot_glyph(draw, slot, ((icon_box[0] + icon_box[2]) / 2,
                                          (icon_box[1] + icon_box[3]) / 2), 21, theme.accent)

            tx = icon_box[2] + 12
            self._caps(draw, (tx, top + 18), slot, DARK_MUTED, size=9.5, tracking=1.6)
            art = data.artifacts.get(slot)
            if art is None:
                draw.text((tx, top + 52), "Not equipped", font=self._font(13, 500),
                          fill=DARK_FAINT, anchor="lm")
                continue
            self._text(draw, (tx, top + 37), f"+{art.level}", self._font(13, 700),
                       (216, 208, 190))
            main_label = art.main_stat or ""
            label_font = self._font(11.5, 500)
            max_label_w = 1221 - tx - 6
            if label_font.getlength(main_label) > max_label_w:
                # Elemental DMG goblets carry the longest labels; shorten gracefully.
                main_label = main_label.replace(" DMG Bonus", " DMG")
            self._text(draw, (tx, top + 56),
                       self._ellipsize(main_label, label_font, max_label_w),
                       label_font, DARK_MUTED, anchor="lm")
            self._text(draw, (tx, top + 80), art.main_value or "--",
                       self._font(21, 700, serif=True), (247, 243, 234), anchor="lm")

            # Substats: two columns x two rows, each with a micro roll-quality bar.
            col_x = [1221, 1331]
            col_w = 104
            for j, (name, value) in enumerate((art.substats or [])[:4]):
                cx0 = col_x[1] if j >= 2 else col_x[0]
                cy = top + 26 + (0 if j % 2 == 0 else 38)
                crit = "crit" in (name or "").lower()
                self._caps(draw, (cx0, cy), _short_substat(name), DARK_MUTED,
                           size=9, tracking=1.1)
                vf = sub_value
                vw = vf.getlength(value)
                draw.text((cx0 + col_w, cy), value, font=vf,
                          fill=theme.accent if crit else (240, 236, 225), anchor="rm")
                _micro_bar(draw, cx0, cy + 7, col_w, _substat_fraction(name, value),
                           theme.accent, bar_h)

            # Per-artifact CV.
            cv = artifact_cv(art.substats or [])
            self._caps(draw, (1475, top + 24), "CV", DARK_FAINT, size=9, tracking=1.6,
                       anchor="mm")
            self._text(draw, (1475, top + 52), f"{cv:.1f}", self._font(19, 700),
                       (247, 243, 234), anchor="mm")

    def _draw_set_bonus(self, draw, data: CardData, theme: _Theme) -> None:
        divider_y = 654
        x0, x1 = RIGHT_L, RIGHT_R
        span = max(1, x1 - x0)
        for x in range(int(x0), int(x1)):
            t = (x - x0) / span
            alpha = int(150 * (1 - t) ** 1.6)
            if alpha > 0:
                draw.point((x, divider_y), fill=(*theme.accent, alpha))
                draw.point((x, divider_y + 1), fill=(*theme.accent, alpha // 2))

        s = data.artifact_set
        if s is None:
            self._caps(draw, (RIGHT_L, 694), "Set bonus", DARK_MUTED, size=10)
            draw.text((RIGHT_L, 726), "No artifact set equipped", font=self._font(13, 500),
                      fill=DARK_FAINT, anchor="lm")
            return

        name_font = self._font(26, 700, serif=True)
        name = self._ellipsize(s.name or "", name_font, 300)
        draw.text((RIGHT_L, 700), name, font=name_font, fill=(247, 243, 234), anchor="ls")

        # Chip shows the active bonus tier (4-PC with 4+ pieces, else 2-PC), not the raw count.
        chip_text = "4-PC" if s.count >= 4 else ("2-PC" if s.count >= 2 else f"{s.count}-PC")
        chip_font = self._font(12, 700)
        cw = int(chip_font.getlength(chip_text)) + 20
        cx1 = RIGHT_R
        draw.rounded_rectangle((cx1 - cw, 676, cx1, 700), 5, fill=(*theme.accent, 255))
        self._text(draw, (cx1 - cw / 2, 689), chip_text, chip_font, (30, 23, 15), anchor="mm")

        # Effect lines from the bundled table (present for supported sets).
        font = self._font(11.5, 400)
        y = 724
        for pieces, text in ((2, s.two_piece), (4, s.four_piece)):
            if not text:
                continue
            self._caps(draw, (RIGHT_L, y), f"{pieces}-PC", DARK_FAINT, size=9.5, tracking=1.4)
            lines = self._wrap(text, font, RIGHT_R - (RIGHT_L + 56), 2)
            yy = y
            for line in lines:
                draw.text((RIGHT_L + 56, yy), line, font=font, fill=(189, 182, 166),
                          anchor="lm")
                yy += 16
            y = yy + 8

    # -- debug -------------------------------------------------------------
    def _draw_debug_overlay(self, draw) -> None:
        regions = {
            "hero": (0, 0, LEFT_W, HEIGHT),
            "identity": (MID_L, 24, MID_R, 174),
            "level": (MID_L, 174, MID_R, 272),
            "weapon": (MID_L, 292, MID_R, 452),
            "attributes": (MID_L, 470, MID_R, 664),
            "talents": (MID_L, 664, MID_R, 812),
            "footer": (MID_L, 812, MID_R, HEIGHT),
            "artifacts": (1010, 0, WIDTH, HEIGHT),
        }
        font = self._font(10, 600)
        for name, box in regions.items():
            draw.rectangle(box, outline=(0, 200, 255), width=1)
            draw.text((box[0] + 3, box[1] + 2), name, font=font, fill=(0, 160, 220))


# -- CRIT value -----------------------------------------------------------
_CRIT_TOKEN = re.compile(r"crit", re.IGNORECASE)


def _stat_number(text: str | None) -> float:
    """Parse the renderer's formatted stat strings ("52,310", "72.4%") into floats."""
    if not text:
        return 0.0
    m = re.search(r"-?\d[\d,]*\.?\d*", text)
    if not m:
        return 0.0
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return 0.0


def _substat_parts(name: str | None, value: str | None) -> tuple[str, float, bool]:
    """(normalised key, magnitude, is_percent) for a formatted substat like ("CRIT Rate", "+7.8%")."""
    key = " ".join((name or "").strip().lower().split())
    raw = (value or "").strip()
    is_percent = raw.endswith("%")
    return key, _stat_number(raw), is_percent


_SHORT_SUBSTAT = {
    "energy recharge": "ER", "elemental mastery": "EM",
    "crit rate": "CRIT Rate", "crit dmg": "CRIT DMG",
    "hp": "HP", "atk": "ATK", "def": "DEF",
    "hp%": "HP%", "atk%": "ATK%", "def%": "DEF%",
}


def _short_substat(name: str | None) -> str:
    key = " ".join((name or "").strip().lower().split())
    return _SHORT_SUBSTAT.get(key, name or "")


def _substat_fraction(name: str | None, value: str | None) -> float:
    """0..1 roll-quality fraction for a substat, against single-roll 5-star maxima."""
    key, magnitude, _ = _substat_parts(name, value)
    cap = _SUBSTAT_CAP.get(key)
    if cap is None and key.endswith("%"):
        cap = _SUBSTAT_CAP.get(key[:-1].strip() + "%") or _SUBSTAT_CAP.get(key[:-1].strip())
    if cap is None:
        cap = _SUBSTAT_CAP.get(key + "%")
    if not cap:
        return 0.35  # unknown scale — draw a modest, neutral bar rather than none
    return max(0.0, min(1.0, magnitude / cap))


def artifact_cv(substats) -> float:
    """CRIT Value (2x CRIT Rate + CRIT DMG) over substats only, per the studio convention."""
    total = 0.0
    for name, value in substats or []:
        key, magnitude, _ = _substat_parts(name, value)
        if key == "crit rate":
            total += 2.0 * magnitude
        elif key == "crit dmg":
            total += magnitude
    return total


def artifact_total_cv(artifacts) -> float:
    total = 0.0
    for art in (artifacts or {}).values():
        if art is not None:
            total += artifact_cv(art.substats)
    return total


def artifact_cv_grade(total_cv: float) -> str:
    for letter, threshold in _CV_GRADES:
        if total_cv >= threshold:
            return letter
    return "D"


def _emphasised_rows(*, hp_v: float, crit_rate: float, crit_dmg: float,
                     energy_recharge: float) -> set[str]:
    """Deterministic stat-emphasis rule, matching the reference studio cards.

    Emphasised (element-coloured) rows: Max HP for HP-scaling characters (>= 40k),
    CRIT Rate >= 50%, CRIT DMG >= 110%, Energy Recharge >= 130%. The elemental DMG Bonus
    row is always emphasised by the caller.
    """
    hot: set[str] = set()
    if hp_v >= 40_000:
        hot.add("hp")
    if crit_rate >= 50.0:
        hot.add("crit_rate")
    if crit_dmg >= 110.0:
        hot.add("crit_dmg")
    if energy_recharge >= 130.0:
        hot.add("er")
    return hot


# -- drawing primitives -----------------------------------------------------------------
def _vertical_gradient(size, top, bottom) -> Image.Image:
    w, h = size
    lut = []
    for i in range(256):
        f = i / 255
        lut.append(tuple(round(top[k] + (bottom[k] - top[k]) * f) for k in range(3)))
    ramp = Image.linear_gradient("L").resize((1, h))
    img = Image.new("RGB", (1, h))
    img.putdata([lut[v] for v in ramp.getdata()])
    return img.resize((w, h)).convert("RGBA")


def _radial_glow(canvas_size, center, ellipse, color_alpha) -> Image.Image:
    """Canvas-sized transparent layer carrying one soft radial glow at ``center``."""
    cw, ch = canvas_size
    ew, eh = ellipse
    ramp = Image.radial_gradient("L").resize((ew, eh), Image.BILINEAR)
    glow = Image.new("RGBA", (ew, eh), (*color_alpha[:3], 0))
    glow.putalpha(ramp.point(lambda v: int(color_alpha[3] * (1 - v / 255))))
    layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    layer.alpha_composite(glow, (round(center[0] - ew / 2), round(center[1] - eh / 2)))
    return layer


@lru_cache(maxsize=8)
def _canvas_base(theme: _Theme) -> Image.Image:
    """The full 1536x864 background: art panel, ivory centre, dark artefacts rail."""
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), IVORY_TOP + (255,))

    # Middle ivory with a soft vertical falloff.
    middle = _vertical_gradient((1010 - LEFT_W, HEIGHT), IVORY_TOP, IVORY_BOTTOM)
    canvas.alpha_composite(middle, (LEFT_W, 0))

    # Left panel: parchment gradient + soft top glow.
    left = _vertical_gradient((LEFT_W, HEIGHT), theme.left_top, theme.left_bottom)
    canvas.alpha_composite(left, (0, 0))
    canvas.alpha_composite(
        _radial_glow((WIDTH, HEIGHT), (LEFT_W // 2, 190), (660, 720), (255, 255, 255, 105)))

    # Right panel: deep element-tinted gradient + faint accent glow, top-right.
    right = _vertical_gradient((WIDTH - 1010, HEIGHT), theme.right_top, theme.right_bottom)
    canvas.alpha_composite(right, (1010, 0))
    canvas.alpha_composite(
        _radial_glow((WIDTH, HEIGHT), (1312, 150), (640, 580), (*theme.accent, 46)))

    # Panel dividers.
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.line((LEFT_W - 0.5, 0, LEFT_W - 0.5, HEIGHT), fill=(23, 19, 16, 62), width=1)
    draw.line((1010.0, 0, 1010.0, HEIGHT), fill=(0, 0, 0, 120), width=1)

    # Fine grain to keep the ivory from feeling flat.
    noise = Image.effect_noise((WIDTH, HEIGHT), 38).point(lambda v: max(0, v - 128) // 9)
    grain = Image.new("RGBA", (WIDTH, HEIGHT), (96, 88, 70, 0))
    grain.putalpha(noise)
    canvas.alpha_composite(grain)
    return canvas


def _place_portrait(base: Image.Image, img, adjustment: Adjustment) -> None:
    """Seat the artwork in the art panel (full-height, centred on its alpha mass)."""
    art = img.convert("RGBA")
    if art.width < 1000:
        image_fitter.paste_into(base, art, (28, 110, LEFT_W - 28, HEIGHT),
                                align="bottom", adjustment=adjustment)
        return

    alpha = art.getchannel("A")
    solid = alpha.point(lambda a: 255 if a > 128 else 0)
    bbox = solid.getbbox()
    if bbox is None:
        return
    columns = list(solid.resize((256, 1), Image.BOX).getdata())
    mass = sum(columns) or 1
    centre_x = sum(i * v for i, v in enumerate(columns)) / mass * art.width / 256

    scale = 838 / max(1, bbox[3] - bbox[1]) * max(0.05, adjustment.scale)
    left = LEFT_W / 2 - centre_x * scale + adjustment.x_offset
    top = 18 - bbox[1] * scale + adjustment.y_offset

    src_x0 = max(0, int(-left / scale))
    src_x1 = min(art.width, int((LEFT_W - left) / scale) + 2)
    src_y0 = max(0, int(-top / scale))
    src_y1 = min(art.height, int((HEIGHT - top) / scale) + 2)
    if src_x1 <= src_x0 or src_y1 <= src_y0:
        return
    part = art.crop((src_x0, src_y0, src_x1, src_y1))
    part = part.resize((max(1, round(part.width * scale)), max(1, round(part.height * scale))),
                       Image.LANCZOS)
    base.alpha_composite(part, (round(left + src_x0 * scale), round(top + src_y0 * scale)))


def _draw_no_portrait(base: Image.Image) -> None:
    """Tasteful empty state: a faint element sigil watermark instead of a broken frame."""
    glyph = _icon("sigil", 190, (36, 31, 22))
    glyph = glyph.point(lambda a: a // 6)
    base.alpha_composite(glyph, (LEFT_W // 2 - 95, 250))


def _dashed_line(draw, xy0, xy1, *, fill, width: int, dash: float, gap: float) -> None:
    x0, y0 = xy0
    x1, y1 = xy1
    length = math.hypot(x1 - x0, y1 - y0)
    if length <= 0:
        return
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    pos = 0.0
    while pos < length:
        end = min(length, pos + dash)
        draw.line((x0 + ux * pos, y0 + uy * pos, x0 + ux * end, y0 + uy * end),
                  fill=fill, width=width)
        pos += dash + gap


def _dashed_circle(draw, cx, cy, r, *, fill, width: int, dash_deg: float, gap_deg: float) -> None:
    bbox = (cx - r, cy - r, cx + r, cy + r)
    angle = 0.0
    while angle < 360.0:
        draw.arc(bbox, angle, min(360.0, angle + dash_deg), fill=fill, width=width)
        angle += dash_deg + gap_deg


def _dotted_leader(draw, x0: float, x1: float, y: float, *, fill) -> None:
    if x1 - x0 < 18:
        return
    x = x0
    while x < x1:
        draw.ellipse((x - 1.25, y - 1.25, x + 1.25, y + 1.25), fill=fill)
        x += 9


def _hexagon_points(cx, cy, r, rot_deg: float = -90.0):
    return [(cx + r * math.cos(math.radians(rot_deg + 60 * i)),
             cy + r * math.sin(math.radians(rot_deg + 60 * i))) for i in range(6)]


def _draw_radar(base, center, r, theme: _Theme, *, top: str, values) -> None:
    """Hexagon radar with dotted rings, element-tinted fill and axis captions."""
    cx, cy = center
    size = (2 * (r + 40), 2 * (r + 40))
    tile = Image.new("RGBA", size, (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(tile)
    tx, ty = r + 40, r + 40  # local origin == center

    ring = (186, 178, 158, 255)
    for frac in (1 / 3, 2 / 3, 1.0):
        tdraw.polygon(_hexagon_points(tx, ty, r * frac), outline=ring)
    for px, py in _hexagon_points(tx, ty, r):
        tdraw.line((tx, ty, px, py), fill=ring, width=1)

    points = _hexagon_points(tx, ty, r)
    poly = [(tx + (px - tx) * v, ty + (py - ty) * v) for (px, py), v in zip(points, values)]
    tdraw.polygon(poly, fill=(*theme.accent, 88), outline=(*theme.accent, 255))
    for px, py in poly:
        tdraw.ellipse((px - 3.4, py - 3.4, px + 3.4, py + 3.4), fill=(*theme.accent, 255))

    base.alpha_composite(tile, (round(cx - tx), round(cy - ty)))

    draw = ImageDraw.Draw(base, "RGBA")
    labels = [top, "CRIT RATE", "CRIT DMG", "ER", "EM", "DMG%"]
    font = _label_font(10, 600)
    for i, label in enumerate(labels):
        angle = math.radians(-90 + 60 * i)
        lx = cx + (r + 21) * math.cos(angle)
        ly = cy + (r + 17) * math.sin(angle)
        draw.text((lx, ly), label, font=font, fill=(138, 131, 117), anchor="mm")


def _draw_slot_glyph(draw, slot: str, center, size: float, color) -> None:
    """Line-art glyph for an artifact slot (Flower/Plume/Sands/Goblet/Circlet)."""
    cx, cy = center
    s = size
    w = 2.5
    col = (*color, 255) if isinstance(color, tuple) else color

    if slot == "flower":
        for i in range(5):
            angle = math.radians(-90 + 72 * i)
            px, py = cx + s * 0.62 * math.cos(angle), cy + s * 0.62 * math.sin(angle)
            pr = s * 0.36
            draw.ellipse((px - pr, py - pr, px + pr, py + pr), outline=col, width=int(w))
        draw.ellipse((cx - s * 0.2, cy - s * 0.2, cx + s * 0.2, cy + s * 0.2),
                     outline=col, width=int(w))
    elif slot == "plume":
        # Rotated-ellipse leaf outline (parametric), a central vein and two barb ticks.
        rot = math.radians(38)
        cos_r, sin_r = math.cos(rot), math.sin(rot)

        def rot_pt(dx, dy):
            return (cx + dx * cos_r - dy * sin_r, cy + dx * sin_r + dy * cos_r)

        leaf = [rot_pt(s * 0.42 * math.cos(a), s * 0.92 * math.sin(a))
                for a in [math.radians(t) for t in range(0, 361, 12)]]
        draw.line(leaf, fill=col, width=int(w), joint="curve")
        draw.line([rot_pt(0, -s * 0.92), rot_pt(0, s * 0.92)], fill=col, width=int(w))
        draw.line([rot_pt(0, -s * 0.30), rot_pt(-s * 0.26, -s * 0.52)], fill=col, width=int(w))
        draw.line([rot_pt(0, s * 0.18), rot_pt(-s * 0.25, -s * 0.08)], fill=col, width=int(w))
        draw.line([rot_pt(0, 0), rot_pt(s * 0.27, -s * 0.22)], fill=col, width=int(w))
    elif slot == "sands":
        top = [(cx - s * 0.62, cy - s * 0.72), (cx + s * 0.62, cy - s * 0.72),
               (cx + s * 0.17, cy), (cx - s * 0.17, cy)]
        bot = [(x, 2 * cy - y) for x, y in top]
        draw.polygon(top, outline=col, width=int(w))
        draw.polygon(bot, outline=col, width=int(w))
        draw.line((cx - s * 0.78, cy - s * 0.86, cx + s * 0.78, cy - s * 0.86), fill=col,
                  width=int(w))
        draw.line((cx - s * 0.78, cy + s * 0.86, cx + s * 0.78, cy + s * 0.86), fill=col,
                  width=int(w))
    elif slot == "goblet":
        draw.line((cx - s * 0.62, cy - s * 0.68, cx + s * 0.62, cy - s * 0.68), fill=col,
                  width=int(w))
        draw.arc((cx - s * 0.62, cy - s * 0.78, cx + s * 0.62, cy + s * 0.22),
                 0, 180, fill=col, width=int(w))
        draw.line((cx, cy + s * 0.22, cx, cy + s * 0.58), fill=col, width=int(w))
        draw.line((cx - s * 0.4, cy + s * 0.72, cx + s * 0.4, cy + s * 0.72), fill=col,
                  width=int(w))
    elif slot == "circlet":
        pts = [(cx - s * 0.68, cy + s * 0.4), (cx - s * 0.47, cy - s * 0.38),
               (cx - s * 0.2, cy + s * 0.02), (cx, cy - s * 0.58),
               (cx + s * 0.2, cy + s * 0.02), (cx + s * 0.47, cy - s * 0.38),
               (cx + s * 0.68, cy + s * 0.4)]
        draw.line(pts, fill=col, width=int(w), joint="curve")
        draw.line((cx - s * 0.68, cy + s * 0.62, cx + s * 0.68, cy + s * 0.62), fill=col,
                  width=int(w))
    else:
        draw.ellipse((cx - s * 0.5, cy - s * 0.5, cx + s * 0.5, cy + s * 0.5),
                     outline=col, width=int(w))


def _micro_bar(draw, x, y, width, fraction: float, color, bar_h: int = 3) -> None:
    segments, gap = 5, 4
    seg_w = (width - gap * (segments - 1)) / segments
    filled = int(round(max(0.0, min(1.0, fraction)) * segments))
    if fraction > 0.05:
        filled = max(1, filled)
    for i in range(segments):
        x0 = x + i * (seg_w + gap)
        if i < filled:
            draw.rounded_rectangle((x0, y, x0 + seg_w, y + bar_h), 1.5, fill=(*color, 255))
        else:
            draw.rounded_rectangle((x0, y, x0 + seg_w, y + bar_h), 1.5,
                                   fill=(255, 255, 255, 26))


def _mean_luminance(img: Image.Image) -> float:
    rgba = img.convert("RGBA")
    solid = rgba.getchannel("A").point(lambda a: 255 if a > 110 else 0)
    if solid.getbbox() is None:
        return 0.0
    gray = ImageOps.grayscale(rgba.convert("RGB"))
    hist = gray.histogram(solid)
    total = sum(hist)
    if not total:
        return 0.0
    return sum(i * v for i, v in enumerate(hist)) / total


def _tint_alpha(img: Image.Image, color) -> Image.Image:
    alpha = img.getchannel("A")
    out = Image.new("RGBA", img.size, (*color[:3], 0))
    out.putalpha(alpha)
    fill = Image.new("RGBA", img.size, (*color[:3], 255))
    out.paste(fill, (0, 0), alpha)
    return out


def _paste_glyph_or_icon(base: Image.Image | None, img, box, theme: _Theme, *,
                         on_dark: bool = True, fallback: str = "") -> None:
    """Contain-fit an icon into ``box``, re-tinting when its luminance fights the background."""
    x0, y0, x1, y1 = box
    box_w, box_h = x1 - x0, y1 - y0
    if img is None:
        if fallback and base is not None:
            _draw_weapon_glyph(ImageDraw.Draw(base, "RGBA"), fallback,
                               ((x0 + x1) / 2, (y0 + y1) / 2), box_h * 0.42, theme.accent)
        return
    art = img.convert("RGBA")
    art = image_fitter.trim_transparent(art)
    if art.width == 0 or art.height == 0:
        return
    lum = _mean_luminance(art)
    if on_dark and lum < 110:
        art = _tint_alpha(art, theme.accent)
    elif not on_dark and lum > 140:
        art = _tint_alpha(art, (36, 31, 22))
    art = image_fitter.fit(art, box_w, box_h, mode="contain")
    px = x0 + (box_w - art.width) // 2
    py = y0 + (box_h - art.height) // 2
    base.alpha_composite(art, (int(px), int(py)))


def _draw_weapon_glyph(draw, weapon_type: str, center, size: float, color) -> None:
    """Minimal line glyph for the weapon panel when no Enka icon is available."""
    cx, cy = center
    s = size
    w = 3
    col = (*color, 255)
    kind = (weapon_type or "").strip().lower()
    if kind == "sword":
        draw.line((cx - s * 0.55, cy + s * 0.55, cx + s * 0.42, cy - s * 0.42), fill=col, width=w)
        draw.line((cx + s * 0.42, cy - s * 0.42, cx + s * 0.72, cy - s * 0.72), fill=col, width=w)
        draw.line((cx - s * 0.28, cy + s * 0.18, cx + s * 0.18, cy + s * 0.64), fill=col, width=w)
        draw.line((cx - s * 0.6, cy + s * 0.3, cx - s * 0.3, cy + s * 0.6), fill=col, width=w)
    elif kind == "claymore":
        draw.line((cx - s * 0.6, cy + s * 0.6, cx + s * 0.45, cy - s * 0.45), fill=col, width=w + 2)
        draw.line((cx + s * 0.45, cy - s * 0.45, cx + s * 0.78, cy - s * 0.78), fill=col, width=w)
        draw.line((cx - s * 0.28, cy + s * 0.12, cx + s * 0.12, cy + s * 0.52), fill=col, width=w)
    elif kind == "polearm":
        draw.line((cx - s * 0.68, cy + s * 0.68, cx + s * 0.52, cy - s * 0.52), fill=col, width=w)
        draw.polygon([(cx + s * 0.52, cy - s * 0.52), (cx + s * 0.85, cy - s * 0.85),
                      (cx + s * 0.38, cy - s * 0.78)], outline=col, width=w)
        draw.line((cx - s * 0.52, cy + s * 0.52, cx - s * 0.34, cy + s * 0.7), fill=col, width=w)
    elif kind == "bow":
        draw.arc((cx - s * 0.7, cy - s * 0.75, cx + s * 0.7, cy + s * 0.75), 300, 60,
                 fill=col, width=w)
        draw.line((cx + s * 0.32, cy - s * 0.78, cx + s * 0.32, cy + s * 0.78), fill=col, width=w)
        draw.line((cx - s * 0.6, cy, cx + s * 0.32, cy), fill=col, width=w)
    elif kind == "catalyst":
        draw.ellipse((cx - s * 0.62, cy - s * 0.62, cx + s * 0.62, cy + s * 0.62),
                     outline=col, width=w)
        draw.polygon([(cx, cy - s * 0.34), (cx + s * 0.34, cy), (cx, cy + s * 0.34),
                      (cx - s * 0.34, cy)], outline=col, width=w)
    else:
        draw.ellipse((cx - s * 0.5, cy - s * 0.5, cx + s * 0.5, cy + s * 0.5),
                     outline=col, width=w)


@lru_cache(maxsize=32)
def _icon(name: str, size: int, color: tuple) -> Image.Image:
    """A bundled line icon (alpha mask) tinted with ``color`` at ``size`` px."""
    path = ICONS_DIR / f"{name}.png"
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    try:
        mask = Image.open(path).convert("L").resize((size, size), Image.LANCZOS)
    except OSError:
        logger.warning("Missing card icon %s", path.name)
        return out
    fill = Image.new("RGBA", (size, size), (*color[:3], 255))
    if len(color) == 4:
        mask = mask.point(lambda a: a * color[3] // 255)
    out.paste(fill, (0, 0), mask)
    return out


_LABEL_FONTS: dict[tuple[int, int], object] = {}
_PROVIDER = None


def _provider():
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = _default_font_provider()
    return _PROVIDER


def _label_font(size: int, weight: int):
    key = (size, weight)
    if key not in _LABEL_FONTS:
        _LABEL_FONTS[key] = _provider()(size, weight)
    return _LABEL_FONTS[key]


def _default_font_provider():
    """Font lookup backed by the bundled variable fonts, cached per (size, weight, family)."""
    from PIL import ImageFont

    from bot.assets import bootstrap

    cache: dict[tuple[int, int, bool], ImageFont.FreeTypeFont] = {}

    def font_for(size: int, weight: int = 400, *, serif: bool = False):
        key = (size, weight, serif)
        if key not in cache:
            paths = [bootstrap.serif_font_path()] if serif else []
            paths.append(bootstrap.font_path())
            for path in paths:
                try:
                    font = ImageFont.truetype(str(path), int(size))
                except (OSError, ValueError):
                    continue
                try:
                    font.set_variation_by_axes([weight])
                except Exception:  # noqa: BLE001 - non-variable build
                    pass
                cache[key] = font
                break
            else:
                cache[key] = ImageFont.load_default(int(size))
        return cache[key]

    return font_for


_RENDERER: CharacterCardRenderer | None = None


def get_card_renderer() -> CharacterCardRenderer:
    """Shared renderer — fonts and static layers are cached, so one instance is reused."""
    global _RENDERER
    if _RENDERER is None:
        _RENDERER = CharacterCardRenderer()
    return _RENDERER
