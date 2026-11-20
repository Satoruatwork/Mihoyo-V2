"""Character showcase card renderer (1536x864 PNG).

The card is drawn entirely in code — there is no baked template to paint over, so nothing
can show through behind a live value. Layout follows the approved editorial design:

    hero (artwork, identity, constellations, level facts) | weapon, attributes, talents |
    artifacts, set bonus | footer ribbon with player + branding

This module performs no I/O and no API calls: it receives an already-normalized
:class:`CardData` and already-fetched images, so the same input always renders the same card.
Every position below is a constant of this design; a new character needs only data.
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from bot.renderer import image_fitter
from bot.renderer.card_data import CardData
from bot.renderer.card_layout import canonical_element
from bot.renderer.image_fitter import DEFAULT_ADJUSTMENT, Adjustment
from bot.utils.logging import get_logger

logger = get_logger(__name__)

WIDTH, HEIGHT = 1536, 864
HERO_W = 600
ICONS_DIR = Path(__file__).resolve().parent / "icons"

# Palette: warm ivory paper, charcoal ink, botanical green, restrained gold.
IVORY = (245, 240, 230)
PANEL = (239, 233, 220)
INK = (36, 34, 29)
INK_2 = (87, 81, 67)
INK_3 = (138, 130, 111)
LINE = (36, 34, 29, 28)
GOLD = (180, 143, 82)
GOLD_DEEP = (164, 126, 62)
GOLD_PALE = (216, 191, 136)
GREEN = (46, 91, 79)
GREEN_2 = (94, 154, 132)
CRIT_GREEN = (47, 110, 91)
MINT = (169, 216, 196)
NIGHT = (13, 21, 19)
CHIP_TEXT = (242, 239, 230)

# Rarity tile gradients (top-left -> bottom-right), matching in-game rarity colours.
_RARITY_TILES = {
    5: ((199, 154, 91), (142, 106, 61)),
    4: ((156, 128, 194), (95, 78, 134)),
    3: ((98, 140, 184), (58, 88, 132)),
}
_DEFAULT_TILE = ((150, 146, 136), (104, 100, 92))

# Stat name (as Enka reports it) -> icon. Unknown names simply render without an icon.
_STAT_ICONS = {
    "hp": "hp", "max hp": "hp", "hp%": "hp",
    "atk": "atk", "atk%": "atk", "base atk": "atk",
    "def": "def", "def%": "def",
    "elemental mastery": "em",
    "crit rate": "crit_rate", "crit dmg": "crit_dmg",
    "energy recharge": "er",
}
_ELEMENT_ICONS = {
    "PYRO": "pyro", "HYDRO": "hydro", "ELECTRO": "electro", "CRYO": "cryo",
    "ANEMO": "anemo", "GEO": "geo", "DENDRO": "dendro",
}
_SLOTS = ("flower", "plume", "sands", "goblet", "circlet")
_TALENT_LABELS = (("normal", "Normal Attack"), ("skill", "Elemental Skill"),
                  ("burst", "Elemental Burst"))


class CharacterCardRenderer:
    """Renders a :class:`CardData` to the showcase PNG."""

    def __init__(self, font_provider=None) -> None:
        self._font_for = font_provider or _default_font_provider()

    # -- public API --------------------------------------------------------
    def render(self, data: CardData, *, debug: bool = False) -> bytes:
        """Render ``data`` to PNG bytes at 1536x864."""
        base = _static_base().copy()
        self._draw_hero(base, data)
        draw = ImageDraw.Draw(base, "RGBA")
        self._draw_weapon(base, draw, data)
        self._draw_stats(base, draw, data)
        self._draw_talents(base, draw, data)
        self._draw_artifacts(base, draw, data)
        self._draw_set_bonus(base, draw, data)
        self._draw_ribbon(base, draw, data)
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

    def _label(self, draw, xy, text, fill=INK_3, size=12) -> float:
        """Small tracked caps label (section/slot captions)."""
        return self._text(draw, xy, text.upper(), self._font(size, 600), fill,
                          tracking=size * 0.18)

    def _heading(self, draw, x, y, width, text) -> None:
        """Serif section heading with a gold diamond and a fading hairline."""
        cy = y + 11
        _diamond(draw, (x + 5, cy), 5, outline=GOLD)
        end = x + 22 + self._text(draw, (x + 22, cy), text, self._font(21, 600, serif=True), INK)
        _hairline(draw, (int(end) + 12, cy, x + width, cy))

    # -- A. hero -----------------------------------------------------------
    def _draw_hero(self, base, data: CardData) -> None:
        hero = _hero_background().copy()
        if data.portrait is not None:
            _place_portrait(hero, data.portrait, data.character_adjustment)
        hero.alpha_composite(_hero_shade())
        base.alpha_composite(hero, (0, 0))

        draw = ImageDraw.Draw(base, "RGBA")
        ch = data.character
        # Right edge: gold hairline with a small diamond at its centre.
        edge = _vertical_fade((1, HEIGHT), (*GOLD_PALE, 140))
        base.alpha_composite(edge, (HERO_W - 1, 0))
        _diamond(draw, (HERO_W, 432), 8, outline=GOLD_PALE, fill=NIGHT)

        # Identity: element + weapon type, name, rarity.
        canon = canonical_element(ch.element)
        tag = " · ".join(t for t in (canon or "", ch.weapon_type.upper()) if t)
        x = 44
        icon = _ELEMENT_ICONS.get(canon or "")
        if icon:
            base.alpha_composite(_icon(icon, 15, MINT), (44, 41))
            x = 67
        self._label(draw, (x, 48), tag, fill=MINT, size=12)

        name = ch.name or ""
        size = 68
        while size > 40 and self._font(size, 600, serif=True).getlength(name) > 500:
            size -= 2
        name_font = self._font(size, 600, serif=True)
        name = self._ellipsize(name, name_font, 500)
        draw.text((46, 116), name, font=name_font, fill=(0, 0, 0, 70), anchor="ls")
        draw.text((44, 114), name, font=name_font, fill=(247, 242, 231), anchor="ls")
        _stars(base, (44, 144), ch.rarity or 0, 15, GOLD_PALE, gap=3)

        self._draw_constellations(base, draw, data)
        self._draw_facts(base, draw, data)

    def _draw_constellations(self, base, draw, data: CardData) -> None:
        nodes = [n for n in data.constellations if n.image is not None]
        for i, node in enumerate(nodes[:6]):
            x, y = 44, 318 + 58 * i
            ring = (*GOLD_PALE, 190) if node.unlocked else (245, 240, 230, 41)
            draw.ellipse((x, y, x + 43, y + 43), fill=(*NIGHT, 184), outline=ring, width=1)
            img = node.image.convert("RGBA")
            if not node.unlocked:
                img = _faded(ImageOps.grayscale(img.convert("RGB")).convert("RGBA"), img, 0.28)
            image_fitter.paste_into(base, img, (x + 8, y + 8, x + 36, y + 36))
            if not node.unlocked:
                bx, by = x + 31, y + 31
                draw.ellipse((bx, by, bx + 16, by + 16), fill=(29, 42, 39),
                             outline=(245, 240, 230, 56))
                base.alpha_composite(_icon("lock", 8, (185, 194, 190)), (bx + 4, by + 4))

    def _draw_facts(self, base, draw, data: CardData) -> None:
        ch = data.character
        label_font = self._font(12, 600)
        value_font = self._font(26, 600)
        small_font = self._font(14, 500)
        facts: list[tuple[str, str, str | None, bool]] = [
            ("LEVEL", str(ch.level), f"/ {ch.max_level}", False),
            ("CONSTELLATION", f"C{ch.constellation}", None, False),
        ]
        if ch.friendship is not None:
            facts.append(("FRIENDSHIP", str(ch.friendship), None, True))

        x = 44
        for i, (key, value, suffix, heart) in enumerate(facts):
            if i:
                draw.line((x, 778, x, 828), fill=(*GOLD_PALE, 82), width=1)
                x += 27
            start = x
            key_w = self._text(draw, (x, 786), key, label_font, (245, 240, 230, 148),
                               tracking=2.3)
            vx = x
            if heart:
                base.alpha_composite(_icon("heart", 15, (231, 169, 160)), (round(vx), 806))
                vx += 22
            vx += self._text(draw, (vx, 813), value, value_font, IVORY)
            if suffix:
                vx += 4 + self._text(draw, (vx + 4, 817), suffix, small_font,
                                     (245, 240, 230, 140))
            x = max(start + key_w, vx) + 26

    # -- D. weapon ---------------------------------------------------------
    def _draw_weapon(self, base, draw, data: CardData) -> None:
        _panel(draw, (640, 40, 996, 188))
        w = data.weapon
        _tile(base, (657, 57, 773, 173), w.rarity if w else None, 12)
        if w is None:
            self._label(draw, (791, 65), "Weapon")
            self._text(draw, (791, 92), "No weapon equipped", self._font(14, 500), INK_3)
            return
        _paste_icon(base, data.weapon_image, (664, 64, 766, 166))

        self._label(draw, (791, 65), "Weapon")
        name_font = self._font(20, 600, serif=True)
        y = 88
        for line in self._wrap(w.name, name_font, 188, 2):
            self._text(draw, (791, y), line, name_font, INK)
            y += 22
        _stars(base, (791, y - 3), w.rarity or 0, 14, GOLD_DEEP, gap=3)

        # Chips: refinement, base ATK, secondary stat.
        x = 791
        chip_font = self._font(13, 600)
        x = self._chip(base, draw, x, 140, w.refinement_text, chip_font, dark=True)
        if w.base_attack:
            x = self._chip(base, draw, x, 140, w.base_attack, chip_font, icon="atk")
        if w.secondary_stat:
            icon = _STAT_ICONS.get(w.secondary_stat_name.strip().lower())
            text = w.secondary_stat if icon else f"{w.secondary_stat_name} {w.secondary_stat}"
            self._chip(base, draw, x, 140, text, chip_font, icon=icon, max_right=990)
        self._text(draw, (791, 178), w.level_text, self._font(13, 500), INK_2)

    def _chip(self, base, draw, x, y, text, font, *, dark=False, icon=None,
              max_right=None) -> int:
        """Rounded value chip; returns the x where the next chip may start."""
        if not text:
            return x
        pad, h = 9, 24
        inner = (17 if icon else 0)
        if max_right is not None:
            text = self._ellipsize(text, font, max_right - x - 2 * pad - inner)
        w = int(font.getlength(text)) + 2 * pad + inner
        if dark:
            draw.rounded_rectangle((x, y, x + w, y + h), 7, fill=GREEN)
        else:
            draw.rounded_rectangle((x, y, x + w, y + h), 7, fill=(255, 255, 255, 140),
                                   outline=LINE)
        tx = x + pad
        if icon:
            base.alpha_composite(_icon(icon, 13, GREEN), (tx, y + 6))
            tx += 17
        self._text(draw, (tx, y + h / 2), text, font, CHIP_TEXT if dark else INK)
        return x + w + 8

    # -- C. attributes -----------------------------------------------------
    def _draw_stats(self, base, draw, data: CardData) -> None:
        self._heading(draw, 640, 214, 356, "Attributes")
        s = data.stats
        canon = canonical_element(data.character.element)
        rows = (
            ("hp", "Max HP", s.hp), ("atk", "ATK", s.atk), ("def", "DEF", s.defense),
            ("em", "Elemental Mastery", s.em), ("crit_rate", "CRIT Rate", s.crit_rate),
            ("crit_dmg", "CRIT DMG", s.crit_dmg), ("er", "Energy Recharge", s.energy_recharge),
            (_ELEMENT_ICONS.get(canon or "", "crit_dmg"), s.elemental_bonus_name,
             s.elemental_bonus),
        )
        name_font, value_font = self._font(15, 500), self._font(16, 600)
        for i, (icon, label, value) in enumerate(rows):
            top = 245 + 38 * i
            cy = top + 19
            base.alpha_composite(_icon(icon, 17, GREEN_2), (640, cy - 8))
            self._text(draw, (669, cy), self._ellipsize(label, name_font, 220), name_font, INK_2)
            self._text(draw, (996, cy), value, value_font, INK, anchor="rm")
            if i < len(rows) - 1:
                draw.line((640, top + 37, 996, top + 37), fill=LINE, width=1)

    # -- E. talents --------------------------------------------------------
    def _draw_talents(self, base, draw, data: CardData) -> None:
        self._heading(draw, 640, 600, 356, "Talents")
        level_font, name_font = self._font(13, 700), self._font(13, 500)
        for i, (key, label) in enumerate(_TALENT_LABELS):
            talent = data.talents.get(key)
            cx = round(640 + 356 / 6 * (2 * i + 1))
            top = 637
            draw.ellipse((cx - 40, top - 5, cx + 40, top + 75), outline=(*GOLD, 72), width=1)
            base.alpha_composite(_talent_disc(), (cx - 35, top))
            draw.ellipse((cx - 35, top, cx + 35, top + 70), outline=(*GOLD, 140), width=1)
            if talent is not None:
                _paste_icon(base, talent.image, (cx - 22, top + 13, cx + 22, top + 57),
                            shadow=False)
                text = str(talent.level)
                bw = max(30, int(level_font.getlength(text)) + 16)
                draw.rounded_rectangle((cx - bw / 2, top + 58, cx + bw / 2, top + 79), 11,
                                       fill=IVORY, outline=(*GOLD, 166))
                self._text(draw, (cx, top + 68.5), text, level_font, INK, anchor="mm")
            self._text(draw, (cx, 733), label, name_font, INK_2, anchor="mm")

    # -- F. artifacts ------------------------------------------------------
    def _draw_artifacts(self, base, draw, data: CardData) -> None:
        self._heading(draw, 1024, 40, 476, "Artifacts")
        main_font, value_font = self._font(13, 500), self._font(22, 600)
        sub_font, sub_value_font = self._font(13, 400), self._font(14, 600)
        plus_font = self._font(11, 700)
        for i, slot in enumerate(_SLOTS):
            top = 75 + 106 * i
            _panel(draw, (1024, top, 1500, top + 98))
            art = data.artifacts.get(slot)
            _tile(base, (1036, top + 11, 1112, top + 87), art.rarity if art else None, 12)
            self._label(draw, (1126, top + 24), slot)
            if art is None:
                self._text(draw, (1126, top + 52), "Not equipped", main_font, INK_3)
                continue
            _paste_icon(base, art.image, (1042, top + 17, 1106, top + 81))
            if art.level:
                text = f"+{art.level}"
                pw = int(plus_font.getlength(text)) + 12
                x1, y1 = 1118, top + 93
                draw.rounded_rectangle((x1 - pw, y1 - 20, x1, y1), 10, fill=INK)
                self._text(draw, (x1 - pw / 2, y1 - 10), text, plus_font, (242, 235, 221),
                           anchor="mm")
            self._text(draw, (1126, top + 46),
                       self._ellipsize(art.main_stat, main_font, 128), main_font, INK_2)
            self._text(draw, (1126, top + 69), art.main_value, value_font, INK)

            draw.line((1266, top + 7, 1266, top + 92), fill=LINE, width=1)
            for j, (name, value) in enumerate(art.substats[:4]):
                cy = top + 17 + 22 * j
                crit = "crit" in name.lower()
                self._text(draw, (1283, cy), self._ellipsize(name, sub_font, 140), sub_font,
                           INK_3)
                self._text(draw, (1485, cy), value, sub_value_font,
                           CRIT_GREEN if crit else INK, anchor="rm")

    # -- G. set bonus ------------------------------------------------------
    def _draw_set_bonus(self, base, draw, data: CardData) -> None:
        _panel(draw, (1024, 614, 1500, 800))
        s = data.artifact_set
        if s is None:
            self._label(draw, (1041, 640), "Set bonus")
            self._text(draw, (1041, 668), "No artifact set equipped", self._font(14, 500), INK_3)
            return
        _tile(base, (1041, 629, 1081, 669), 5, 9)
        _paste_icon(base, s.image, (1044, 632, 1078, 666), shadow=False)
        self._label(draw, (1093, 639), "Set bonus")

        chip_font = self._font(13, 600)
        count = f"{s.count} / 5 equipped"
        cw = int(chip_font.getlength(count)) + 18
        draw.rounded_rectangle((1483 - cw, 637, 1483, 661), 7, fill=(255, 255, 255, 140),
                               outline=LINE)
        self._text(draw, (1483 - cw / 2, 649), count, chip_font, INK, anchor="mm")
        name_font = self._font(19, 600, serif=True)
        self._text(draw, (1093, 658), self._ellipsize(s.name, name_font, 1483 - cw - 1105),
                   name_font, INK)

        # Bonus rows. Descriptions are shown only when the data provides them; otherwise
        # the row states whether the bonus is active, which follows directly from the count.
        rows = [
            (2, s.count >= 2, s.two_piece or ("Active" if s.count >= 2 else "Requires 2 pieces")),
            (4, s.count >= 4, s.four_piece or ("Active" if s.count >= 4 else "Requires 4 pieces")),
        ]
        for name, pieces in s.others:
            state = "2-piece bonus active" if pieces >= 2 else "no bonus active"
            rows.append((pieces, pieces >= 2, f"{name} — {state}"))

        text_font = self._font(13, 400)
        pc_font = self._font(11, 700)
        y = 680
        for pieces, active, text in rows:
            lines = self._wrap(text, text_font, 368, 2)
            height = max(20, 18 * len(lines))
            if y + height > 790:
                break
            if active:
                draw.rounded_rectangle((1041, y, 1105, y + 20), 6, fill=GREEN)
            else:
                draw.rounded_rectangle((1041, y, 1105, y + 20), 6, outline=LINE)
            self._text(draw, (1073, y + 10), f"{pieces}-PIECE", pc_font,
                       CHIP_TEXT if active else INK_3, anchor="mm", tracking=0.6)
            for k, line in enumerate(lines):
                self._text(draw, (1115, y + 9 + 18 * k), line, text_font,
                           INK_2 if active else INK_3)
            y += height + 11

    # -- H/I. footer ribbon --------------------------------------------------
    def _draw_ribbon(self, base, draw, data: CardData) -> None:
        _hairline(draw, (640, 818, 1500, 818), fade=False)
        cy = 838
        bold, regular = self._font(13, 600), self._font(13, 500)
        x = 640
        if data.player_name:
            x += self._text(draw, (x, cy), data.player_name, bold, INK)
        if data.player_uid:
            prefix = " · UID " if data.player_name else "UID "
            x += self._text(draw, (x, cy), f"{prefix}{data.player_uid}", regular, INK_3)
        if x > 640:
            _diamond(draw, (x + 23, cy), 3, fill=(*GOLD, 180))
            x += 46
        x += self._text(draw, (x, cy), "CRIT Value ", regular, INK_3)
        self._text(draw, (x, cy), data.stats.crit_value, bold, INK)

        # Branding, right-aligned.
        serif = self._font(15, 600, serif=True)
        serif_light = self._font(15, 500, serif=True)
        tail = "· Powered by Lauma"
        right = 1500
        tail_w = self._text(draw, (right, cy), tail, serif_light, INK_3, anchor="rm",
                            tracking=0.3)
        lead_w = self._text(draw, (right - tail_w - 6, cy), "Built with Passion", serif, INK_2,
                            anchor="rm", tracking=0.9)
        base.alpha_composite(_icon("sigil", 16, GOLD),
                             (int(right - tail_w - lead_w - 6 - 26), cy - 8))

    # -- debug -------------------------------------------------------------
    def _draw_debug_overlay(self, draw) -> None:
        """Outline the major regions. Development only — never in production output."""
        regions = {
            "hero": (0, 0, HERO_W, HEIGHT), "weapon": (640, 40, 996, 188),
            "stats": (640, 214, 996, 549), "talents": (640, 600, 996, 745),
            "artifacts": (1024, 40, 1500, 597), "set": (1024, 614, 1500, 800),
            "ribbon": (640, 818, 1500, 848),
        }
        font = self._font(10, 600)
        for name, box in regions.items():
            draw.rectangle(box, outline=(0, 200, 255), width=1)
            draw.text((box[0] + 3, box[1] + 2), name, font=font, fill=(0, 160, 220))


# -- drawing primitives ----------------------------------------------------------------
def _panel(draw, box) -> None:
    draw.rounded_rectangle(box, 14, fill=(*PANEL, 158), outline=LINE, width=1)


def _hairline(draw, box, *, fade: bool = True) -> None:
    """1px horizontal rule; fades out towards the right when ``fade``."""
    x0, y, x1, _ = box
    if not fade:
        draw.line((x0, y, x1, y), fill=LINE, width=1)
        return
    span = max(1, x1 - x0)
    for x in range(int(x0), int(x1)):
        alpha = int(LINE[3] * (1 - (x - x0) / span))
        if alpha:
            draw.point((x, y), fill=(*LINE[:3], alpha))


def _diamond(draw, center, radius, *, outline=None, fill=None) -> None:
    cx, cy = center
    pts = [(cx, cy - radius), (cx + radius, cy), (cx, cy + radius), (cx - radius, cy)]
    draw.polygon(pts, fill=fill, outline=outline)


def _stars(base, xy, count: int, size: int, color, gap: int = 3) -> None:
    x, y = xy
    star = _icon("star", size, color)
    for _ in range(max(0, min(count, 5))):
        base.alpha_composite(star, (int(x), int(y)))
        x += size + gap


def _faded(img: Image.Image, original: Image.Image, opacity: float) -> Image.Image:
    """``img`` carrying ``original``'s alpha scaled by ``opacity``."""
    alpha = original.getchannel("A").point(lambda a: int(a * opacity))
    img.putalpha(alpha)
    return img


def _tile(base, box, rarity, radius) -> None:
    """Rounded rarity tile with a soft inner highlight."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    top, bottom = _RARITY_TILES.get(rarity or 0, _DEFAULT_TILE)
    tile = _diagonal_gradient((w, h), top, bottom)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=255)
    tile.putalpha(mask)
    ImageDraw.Draw(tile).rounded_rectangle((0, 0, w - 1, h - 1), radius,
                                           outline=(255, 255, 255, 46), width=1)
    base.alpha_composite(tile, (x0, y0))


def _paste_icon(base, img, box, *, shadow: bool = True) -> None:
    """Contain-fit an icon into ``box`` (never stretched), with an optional soft shadow."""
    if img is None:
        return
    x0, y0, x1, y1 = box
    art = image_fitter.fit(image_fitter.trim_transparent(img.convert("RGBA")),
                           x1 - x0, y1 - y0, mode="contain")
    px = x0 + (x1 - x0 - art.width) // 2
    py = y0 + (y1 - y0 - art.height) // 2
    if shadow:
        alpha = art.getchannel("A").point(lambda a: a * 64 // 255)
        pad = 6
        sh = Image.new("RGBA", (art.width + 2 * pad, art.height + 2 * pad), (0, 0, 0, 0))
        sh.paste((0, 0, 0, 255), (pad, pad), alpha)
        sh = sh.filter(ImageFilter.GaussianBlur(2))
        base.alpha_composite(sh, (px - pad, py - pad + 2))
    base.alpha_composite(art, (px, py))


def _place_portrait(hero: Image.Image, img, adjustment: Adjustment) -> None:
    """Seat the artwork in the hero panel without distortion.

    Enka splash sheets span the full 2048x1024 height, but glow and effects reach the edges.
    Solid pixels (alpha > 128) isolate the figure: its bounds are scaled to a fixed height so
    head and feet stay inside the panel, and its horizontal mass is centred in the hero. A
    small non-splash fallback (front icon) is contain-fitted instead of being upscaled.
    """
    art = img.convert("RGBA")
    if art.width < 1000:
        image_fitter.paste_into(hero, art, (70, 170, 560, 770), align="bottom",
                                adjustment=adjustment)
        return
    alpha = art.getchannel("A")
    solid = alpha.point(lambda a: 255 if a > 128 else 0)
    bbox = solid.getbbox()
    if bbox is None:
        return
    columns = list(solid.resize((256, 1), Image.BOX).getdata())
    mass = sum(columns) or 1
    centre_x = sum(i * v for i, v in enumerate(columns)) / mass * art.width / 256

    scale = 787 / max(1, bbox[3] - bbox[1]) * max(0.05, adjustment.scale)
    left = 314 - centre_x * scale + adjustment.x_offset
    top = 35 - bbox[1] * scale + adjustment.y_offset

    # Resize only the part of the sheet that lands inside the panel.
    src_x0 = max(0, int(-left / scale))
    src_x1 = min(art.width, int((HERO_W - left) / scale) + 2)
    src_y0 = max(0, int(-top / scale))
    src_y1 = min(art.height, int((HEIGHT - top) / scale) + 2)
    if src_x1 <= src_x0 or src_y1 <= src_y0:
        return
    part = art.crop((src_x0, src_y0, src_x1, src_y1))
    part = part.resize((max(1, round(part.width * scale)), max(1, round(part.height * scale))),
                       Image.LANCZOS)
    hero.alpha_composite(part, (round(left + src_x0 * scale), round(top + src_y0 * scale)))


# -- cached static layers --------------------------------------------------------------
@lru_cache(maxsize=64)
def _icon(name: str, size: int, color: tuple) -> Image.Image:
    """A bundled line icon (alpha mask) tinted with ``color`` at ``size`` px."""
    path = ICONS_DIR / f"{name}.png"
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    try:
        mask = Image.open(path).convert("L").resize((size, size), Image.LANCZOS)
    except OSError:
        logger.warning("Missing card icon %s", path.name)
        return out
    fill = Image.new("RGBA", (size, size), color[:3] + (255,))
    if len(color) == 4:
        mask = mask.point(lambda a: a * color[3] // 255)
    out.paste(fill, (0, 0), mask)
    return out


def _lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _gradient_lut(stops) -> list[tuple[int, int, int]]:
    """256-entry colour ramp through ``stops`` [(position 0..1, rgb), ...]."""
    lut = []
    for i in range(256):
        t = i / 255
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if t <= p1:
                lut.append(_lerp(c0, c1, (t - p0) / max(1e-6, p1 - p0)))
                break
        else:
            lut.append(stops[-1][1])
    return lut


def _apply_lut(gray: Image.Image, lut) -> Image.Image:
    channels = [gray.point([c[k] for c in lut]) for k in range(3)]
    return Image.merge("RGB", channels).convert("RGBA")


def _radial(canvas, ellipse, center) -> Image.Image:
    """Radial falloff (0 at ``center`` -> 255 at the ellipse edge and beyond) on ``canvas``.

    Built by pasting so regions outside the gradient stay 255; cropping out of bounds would
    fill them with 0, i.e. full intensity, and band the background.
    """
    ramp = Image.radial_gradient("L").resize(ellipse, Image.BILINEAR)
    out = Image.new("L", canvas, 255)
    out.paste(ramp, (round(center[0] - ellipse[0] / 2), round(center[1] - ellipse[1] / 2)))
    return out


def _diagonal_gradient(size, top, bottom) -> Image.Image:
    w, h = size
    ramp = Image.linear_gradient("L").rotate(-30, expand=True, resample=Image.BILINEAR)
    side = max(ramp.size)
    ramp = ramp.crop(((ramp.width - side * 0.6) / 2, (ramp.height - side * 0.6) / 2,
                      (ramp.width + side * 0.6) / 2, (ramp.height + side * 0.6) / 2))
    ramp = ramp.resize((w, h), Image.BILINEAR)
    return _apply_lut(ramp, _gradient_lut([(0, top), (1, bottom)]))


def _vertical_fade(size, color) -> Image.Image:
    """A strip whose alpha fades in and out at both ends (20%..80% fully opaque)."""
    w, h = size
    strip = Image.new("RGBA", (w, h), color[:3] + (0,))
    alpha = Image.new("L", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        k = min(1.0, t / 0.2, (1 - t) / 0.2)
        alpha.putpixel((0, y), int(color[3] * max(0.0, k)))
    strip.putalpha(alpha.resize((w, h)))
    return strip


@lru_cache(maxsize=1)
def _hero_background() -> Image.Image:
    """Deep botanical radial gradient behind the artwork."""
    ramp = _radial((HERO_W, HEIGHT), (1040, 1120), (HERO_W * 0.56, HEIGHT * 0.44))
    lut = _gradient_lut([(0, (40, 72, 64)), (0.55, (22, 39, 31)), (1, NIGHT)])
    return _apply_lut(ramp, lut)


@lru_cache(maxsize=1)
def _hero_shade() -> Image.Image:
    """Top, bottom and left darkening so hero text stays readable over any artwork."""
    rows = Image.new("L", (1, HEIGHT))
    for y in range(HEIGHT):
        t = y / HEIGHT
        top = 0.78 * max(0.0, 1 - t / 0.24)
        b = 1 - t
        if b <= 0.13:
            bottom = 0.96 - (0.96 - 0.7) * (b / 0.13)
        else:
            bottom = 0.7 * max(0.0, 1 - (b - 0.13) / 0.17)
        rows.putpixel((0, y), int(255 * (1 - (1 - top) * (1 - bottom))))
    cols = Image.new("L", (HERO_W, 1))
    for x in range(HERO_W):
        cols.putpixel((x, 0), int(255 * 0.55 * max(0.0, 1 - (x / HERO_W) / 0.22)))
    # Screen-combine the vertical and horizontal falloffs: 1 - (1 - a)(1 - b).
    shade = ImageChops.screen(rows.resize((HERO_W, HEIGHT)), cols.resize((HERO_W, HEIGHT)))
    layer = Image.new("RGBA", (HERO_W, HEIGHT), NIGHT + (255,))
    layer.putalpha(shade)
    return layer


@lru_cache(maxsize=1)
def _talent_disc() -> Image.Image:
    ramp = Image.radial_gradient("L").resize((112, 112), Image.BILINEAR)
    ramp = ramp.crop((21, 14, 91, 84))  # centre at 50% x / 38% y of the 70px disc
    disc = _apply_lut(ramp, _gradient_lut([(0, (58, 111, 97)), (1, (29, 58, 51))]))
    mask = Image.new("L", (70, 70), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 69, 69), fill=255)
    disc.putalpha(mask)
    return disc


@lru_cache(maxsize=1)
def _static_base() -> Image.Image:
    """Ivory paper with soft light falloff and fine grain. Built once, copied per render."""
    base = Image.new("RGBA", (WIDTH, HEIGHT), IVORY + (255,))
    glow = _radial((WIDTH, HEIGHT), (2400, 1400), (WIDTH * 0.85, HEIGHT * 0.10))
    light = Image.new("RGBA", (WIDTH, HEIGHT), (255, 255, 255, 0))
    light.putalpha(glow.point(lambda v: int(140 * max(0.0, 1 - v / 255 / 0.6))))
    base.alpha_composite(light)
    warm = _radial((WIDTH, HEIGHT), (1800, 1200), (WIDTH * 0.70, HEIGHT * 1.10))
    tone = Image.new("RGBA", (WIDTH, HEIGHT), (181, 160, 120, 0))
    tone.putalpha(warm.point(lambda v: int(46 * max(0.0, 1 - v / 255 / 0.65))))
    base.alpha_composite(tone)
    noise = Image.effect_noise((WIDTH, HEIGHT), 48).point(lambda v: max(0, v - 128) // 7)
    grain = Image.new("RGBA", (WIDTH, HEIGHT), (120, 108, 88, 0))
    grain.putalpha(noise)
    base.alpha_composite(grain)
    return base


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
                    font = ImageFont.truetype(str(path), size)
                except (OSError, ValueError):
                    continue
                try:
                    font.set_variation_by_axes([weight])
                except Exception:  # noqa: BLE001 - non-variable build
                    pass
                cache[key] = font
                break
            else:
                cache[key] = ImageFont.load_default(size)
        return cache[key]

    return font_for


_RENDERER: CharacterCardRenderer | None = None


def get_card_renderer() -> CharacterCardRenderer:
    """Shared renderer — fonts and static layers are cached, so one instance is reused."""
    global _RENDERER
    if _RENDERER is None:
        _RENDERER = CharacterCardRenderer()
    return _RENDERER
