"""Pillow rendering backend — placeholder layouts.

This phase intentionally produces simple, functional placeholder cards: a background,
optional artwork/frame slots pulled via the AssetLoader, and text blocks driven by the
domain data. The goal is a working rendering *pipeline* that commands can already call;
the premium visual design is a later phase and only replaces the drawing code here.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from bot.assets import bootstrap
from bot.assets.loader import AssetLoader, get_asset_loader
from bot.renderer import card_layout
from bot.renderer.base import Renderer
from bot.renderer.context import (
    AbyssCardContext,
    CharacterCardContext,
    TheaterCardContext,
)
from bot.translations.i18n import t
from bot.utils.logging import get_logger

logger = get_logger(__name__)

# Element FIGHT_PROP keys for the elemental damage bonus row.
_ELEM_DMG_PROP = {
    "PYRO": "FIGHT_PROP_FIRE_ADD_HURT",
    "HYDRO": "FIGHT_PROP_WATER_ADD_HURT",
    "ELECTRO": "FIGHT_PROP_ELEC_ADD_HURT",
    "CRYO": "FIGHT_PROP_ICE_ADD_HURT",
    "ANEMO": "FIGHT_PROP_WIND_ADD_HURT",
    "GEO": "FIGHT_PROP_ROCK_ADD_HURT",
    "DENDRO": "FIGHT_PROP_GRASS_ADD_HURT",
}

# Ascension tier -> max level, matching the game's progression.
_ASCENSION_MAX_LEVEL = {0: 20, 1: 40, 2: 50, 3: 60, 4: 70, 5: 80, 6: 90}

# Weapon secondary stats are percentages except EM (Enka names ATK% just "ATK").
_FLAT_SUB_STATS = ("elemental mastery",)


def _weapon_max_level(weapon) -> int:
    """Max level for a weapon's ascension tier, falling back to its current level."""
    return _ASCENSION_MAX_LEVEL.get(getattr(weapon, "ascension", None), weapon.level)


def _weapon_sub_text(name: str | None, value: float) -> str:
    """Format a weapon's secondary stat; percent unless it is one of the flat stats."""
    label = (name or "").strip().lower()
    is_flat = any(label == flat or label.endswith(f" {flat}") for flat in _FLAT_SUB_STATS)
    return f"{value:,.0f}" if is_flat else f"{value:.1f}%"


def _stat_value(stat, *, signed: bool) -> str:
    """Format an artifact stat exactly as the reference card does.

    Percentages get one decimal and a '%'; flat values are thousands-separated integers.
    Substats carry a leading '+' (they are gains); a main stat does not.
    """
    value = getattr(stat, "value", None)
    if value is None:
        return "--"
    if getattr(stat, "is_percent", False):
        text = f"{value:.1f}%"
    else:
        text = f"{value:,.0f}"
    return f"+{text}" if signed else text


# The abyss/theater cards still draw on their own portrait-oriented canvas; the character
# profile card uses the fixed template size in card_layout.CARD_SIZE.
_CARD_SIZE = (900, 1200)
_BG = (30, 31, 41, 255)
_PANEL = (40, 42, 54, 255)
_ACCENT = (98, 114, 164, 255)
_TEXT = (248, 248, 242, 255)
_MUTED = (139, 145, 176, 255)


class PillowRenderer(Renderer):
    def __init__(self, assets: AssetLoader | None = None) -> None:
        self._assets = assets or get_asset_loader()
        self._font_cache: dict[int, ImageFont.ImageFont] = {}

    def warmup(self) -> None:
        """Decode the card template and common font sizes once, at startup."""
        try:
            self._template_base()  # populates the in-memory template cache
            for size in (20, 24, 28, 34, 40):
                self._pfont(size)
            logger.info("Renderer warmup complete (template + fonts cached)")
        except Exception as exc:  # noqa: BLE001 - warmup is best-effort
            logger.debug("Renderer warmup skipped: %s", exc)

    # -- fonts -------------------------------------------------------------
    def _font(self, size: int) -> ImageFont.ImageFont:
        if size not in self._font_cache:
            try:
                # Prefer a bundled/ui font if provided; otherwise Pillow's default.
                path = self._assets.resolve("ui", f"font_{size}.ttf") or self._assets.resolve("ui", "font.ttf")
                self._font_cache[size] = (
                    ImageFont.truetype(str(path), size) if path else ImageFont.load_default()
                )
            except (OSError, ValueError):
                self._font_cache[size] = ImageFont.load_default()
        return self._font_cache[size]

    # -- canvas helpers ----------------------------------------------------
    def _canvas(self, ctx) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("RGBA", _CARD_SIZE, _BG)
        # Optional background asset (falls back to placeholder internally).
        if getattr(ctx, "background", None):
            bg = self._assets.load("backgrounds", ctx.background, size=_CARD_SIZE)
            img.alpha_composite(bg)
        draw = ImageDraw.Draw(img)
        return img, draw

    def _panel(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
        draw.rectangle(box, fill=_PANEL, outline=_ACCENT, width=2)

    def _text(self, draw, xy, text, *, size=28, color=_TEXT) -> int:
        draw.text(xy, text, font=self._font(size), fill=color)
        return xy[1] + size + 10

    def _to_png(self, img: Image.Image) -> bytes:
        buf = io.BytesIO()
        img.convert("RGBA").save(buf, format="PNG")
        return buf.getvalue()

    # ==================================================================
    #  Premium character profile card (fixed template + live data)
    # ==================================================================
    def _pfont(self, size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
        """Load the bundled NotoSansSC at a size/weight (falls back to default)."""
        key = (size, weight)
        cache = getattr(self, "_pfont_cache", None)
        if cache is None:
            cache = {}
            self._pfont_cache = cache
        if key not in cache:
            try:
                font = ImageFont.truetype(str(bootstrap.font_path()), size)
                try:
                    font.set_variation_by_axes([weight])
                except Exception:  # noqa: BLE001 - non-variable fallback
                    pass
                cache[key] = font
            except (OSError, ValueError):
                cache[key] = ImageFont.load_default()
        return cache[key]

    def _fit_font(self, draw, text, max_width, base_size, weight=400):
        """Return a font shrunk until ``text`` fits ``max_width`` (auto-resize, no overflow)."""
        size = base_size
        while size > 10:
            font = self._pfont(size, weight)
            if draw.textlength(text, font=font) <= max_width:
                return font
            size -= 2
        return self._pfont(size, weight)

    @staticmethod
    def _fmt(value, *, percent=False, decimals=0):
        if value is None:
            return "--"
        if percent:
            return f"{value:.1f}%"
        if decimals:
            return f"{value:,.{decimals}f}"
        return f"{value:,.0f}"

    def _draw_fit(self, draw, xy, text, *, max_width, size, weight=400, color=(60, 52, 40),
                  anchor="la"):
        font = self._fit_font(draw, text, max_width, size, weight)
        draw.text(xy, text, font=font, fill=color, anchor=anchor)

    def _stars(self, draw, xy, count, *, size=18, color=(214, 168, 74), anchor="la"):
        draw.text(xy, "★" * max(0, int(count or 0)), font=self._pfont(size, 500), fill=color,
                  anchor=anchor)

    _PORTRAIT_FILL = 1.0  # fill the frame window fully (pill mask crops the overflow)

    def _fit_portrait_ellipse(self, base: Image.Image, portrait: Image.Image | None,
                              box, glow) -> None:
        """Composite the character into the frame's pill-shaped inner window.

        The layer starts as an *opaque* element-tinted backdrop, which erases the template's
        baked "CHARACTER IMAGE PLACEHOLDER" text/emblem completely, then the alpha-cropped art
        is cover-fit on top. The whole layer is clipped to a rounded-rectangle (stadium) mask
        matching the frame window, so the character sits *inside* the frame rather than pasted
        on top of the placeholder, and never overflows the border.
        """
        left, top, right, bottom = box
        w, h = right - left, bottom - top
        radius = min(w, h) // 2  # stadium: fully rounded ends

        # Opaque dark base ERASES the baked placeholder; a soft element glow sits over it.
        layer = Image.new("RGBA", (w, h), (18, 17, 24, 255))
        glow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(glow_layer).rounded_rectangle(
            [0, 0, w - 1, h - 1], radius=radius, fill=(*glow, 190))
        layer.alpha_composite(glow_layer.filter(ImageFilter.GaussianBlur(14)))

        if portrait is not None:
            art = portrait.convert("RGBA")
            # Tight-crop to the character's alpha bounds so transparent margins don't shrink it.
            alpha_bbox = art.getchannel("A").getbbox()
            if alpha_bbox:
                art = art.crop(alpha_bbox)
            pw, ph = art.size
            # Cover-fit to fill the frame window: preserve aspect, high-quality LANCZOS.
            scale = max(w / pw, h / ph) * self._PORTRAIT_FILL
            new = art.resize((max(1, round(pw * scale)), max(1, round(ph * scale))), Image.LANCZOS)
            # Centre horizontally; bias vertically toward the top (faces/upper body).
            nx = max(0, (new.width - w) // 2)
            ny = max(0, int((new.height - h) * 0.08))
            cropped = new.crop((nx, ny, nx + min(w, new.width), ny + min(h, new.height)))
            paste_x = (w - cropped.width) // 2
            layer.alpha_composite(cropped, (max(0, paste_x), 0))

        # Rounded-rectangle (stadium) mask matching the frame window.
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
        base.paste(layer, (left, top), mask)

    @staticmethod
    def _circle_icon(img: Image.Image, diameter: int) -> Image.Image:
        """Return the icon scaled to ``diameter`` and clipped to a circle (anti-aliased)."""
        icon = img.convert("RGBA")
        # Cover-fit into the circle box.
        iw, ih = icon.size
        scale = max(diameter / iw, diameter / ih)
        icon = icon.resize((max(1, round(iw * scale)), max(1, round(ih * scale))), Image.LANCZOS)
        left = (icon.width - diameter) // 2
        top = (icon.height - diameter) // 2
        icon = icon.crop((left, top, left + diameter, top + diameter))
        mask = Image.new("L", (diameter, diameter), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, diameter - 1, diameter - 1], fill=255)
        # Combine with the icon's own alpha so transparent icons stay transparent.
        mask = Image.composite(icon.getchannel("A"), Image.new("L", mask.size, 0), mask)
        out = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
        out.paste(icon, (0, 0), mask)
        return out

    def _paste_icon(self, base, icons, url, box, *, ring=None, ring_width=3, fit=False, erase=None):
        """Composite a pre-fetched icon (by URL) centred in ``box`` = (cx, cy, diameter).

        ``erase`` (an RGB colour) fills the icon's circle first, wiping the template's baked
        placeholder emblem so a transparent PNG icon doesn't sit on top of it.
        """
        cx, cy, d = box
        x0, y0 = cx - d // 2, cy - d // 2
        if erase is not None:
            ImageDraw.Draw(base).ellipse([x0, y0, x0 + d, y0 + d], fill=(*erase, 255))
        if ring is not None:
            ImageDraw.Draw(base).ellipse([x0 - 2, y0 - 2, x0 + d + 1, y0 + d + 1],
                                         outline=(*ring, 255), width=ring_width)
        img = icons.get(url) if url else None
        if img is None:
            return False
        if fit:  # square-fit (weapon/artifact icons already have transparent margins)
            icon = img.convert("RGBA")
            iw, ih = icon.size
            scale = min(d / iw, d / ih)
            icon = icon.resize((max(1, round(iw * scale)), max(1, round(ih * scale))), Image.LANCZOS)
            base.alpha_composite(icon, (cx - icon.width // 2, cy - icon.height // 2))
        else:
            base.alpha_composite(self._circle_icon(img, d), (x0, y0))
        return True

    def _draw_constellations(self, base, draw, character, icons, theme) -> None:
        """Render the 6 constellation nodes with real lock state (C-level from Akasha)."""
        nodes = character.constellations or []
        unlocked_count = character.constellation
        accent = theme["accent"]
        for i, (cx, cy) in enumerate(card_layout.CONSTELLATION_NODES):
            d = card_layout.CONSTELLATION_NODE_RADIUS * 2
            x0, y0 = cx - d // 2, cy - d // 2
            node = nodes[i] if i < len(nodes) else None
            unlocked = node.unlocked if node is not None else (i < unlocked_count)
            # Replace the baked node: dark disc base so template lock/emblem never shows through.
            draw.ellipse([x0, y0, x0 + d, y0 + d], fill=(24, 22, 28, 255),
                         outline=(*accent, 255) if unlocked else (90, 86, 96, 255), width=2)
            icon_img = icons.get(node.icon) if (node and node.icon) else None
            if icon_img is not None:
                glyph = self._circle_icon(icon_img, d - 8)
                if not unlocked:  # locked -> dim + desaturate
                    from PIL import ImageEnhance
                    glyph = ImageEnhance.Brightness(glyph.convert("RGBA")).enhance(0.35)
                base.alpha_composite(glyph, (x0 + 4, y0 + 4))
            elif not unlocked:
                draw.text((cx, cy), "🔒", font=self._pfont(20), fill=(150, 146, 156), anchor="mm")

    def _elemental_bonus(self, stats, element):
        """Return the character's elemental DMG bonus as a percentage, or None."""
        if stats is None:
            return None
        extra = getattr(stats, "extra", {}) or {}
        key = _ELEM_DMG_PROP.get(card_layout.canonical_element(element) or "")
        # Prefer the character's own on-element DMG bonus when present. Only when it is
        # absent do we fall back to the largest *_ADD_HURT — otherwise a larger off-element
        # bonus (e.g. Physical DMG from artifacts) would override the on-element value.
        if key and key in extra:
            return extra[key] * 100.0
        candidates = [v for k, v in extra.items() if k.endswith("_ADD_HURT")]
        if not candidates:
            return None
        return max(candidates) * 100.0

    def _dark_luxury_canvas(self, theme: dict[str, tuple[int, int, int]]) -> Image.Image:
        """Create a 1280x720 dark obsidian canvas with subtle elemental ambient glow."""
        w, h = card_layout.CARD_SIZE
        base = Image.new("RGBA", (w, h), (16, 15, 20, 255))
        glow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow_layer)
        gr, gg, gb = theme["glow"]
        # Ambient glow behind portrait
        gdraw.ellipse((60, 40, 440, 680), fill=(gr, gg, gb, 36))
        # Subtle top-right ambient glow
        gdraw.ellipse((860, -120, 1340, 320), fill=(gr, gg, gb, 20))
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=70))
        base.alpha_composite(glow_layer)
        return base

    def render_profile_card(self, ctx: CharacterCardContext) -> bytes:
        c = ctx.character
        theme = card_layout.theme_for(c.element if c else None)
        base = self._dark_luxury_canvas(theme)

        # Full-bleed left character portrait, seamlessly blended into the dark canvas.
        portrait = ctx.portrait if isinstance(ctx.portrait, Image.Image) else None
        if portrait is not None:
            pw, ph = 540, 720
            p_copy = portrait.convert("RGBA")
            scale = max(pw / p_copy.width, ph / p_copy.height)
            nw, nh = int(p_copy.width * scale), int(p_copy.height * scale)
            p_copy = p_copy.resize((nw, nh), Image.Resampling.LANCZOS)
            left_crop = max(0, (nw - pw) // 2)
            top_crop = max(0, (nh - ph) // 4)
            p_copy = p_copy.crop((left_crop, top_crop, left_crop + pw, top_crop + ph))
            # Soft horizontal fade on the right edge so it blends into the dark UI
            mask = Image.new("L", (pw, ph), 255)
            mdraw = ImageDraw.Draw(mask)
            for x in range(pw - 140, pw):
                alpha = int(255 * (pw - x) / 140)
                mdraw.line((x, 0, x, ph), fill=alpha)
            base.paste(p_copy, (0, 0), mask)

        draw = ImageDraw.Draw(base)
        if c is None:
            return self._to_png(base)

        accent = theme["accent"]
        glass_bg = (26, 24, 32, 215)
        glass_border = (110, 102, 118, 200)
        divider_col = (58, 54, 68, 200)
        ivory = (248, 244, 238)
        muted = (176, 170, 182)
        gold = (236, 194, 96)

        def draw_glass(box, *, radius=14, border=glass_border, fill=glass_bg, width=1):
            draw.rounded_rectangle(box, radius=radius, fill=fill, outline=border, width=width)

        # -- left showcase: element, name, stars, constellations, level, UID --
        elem_label = (card_layout.canonical_element(c.element) or c.element or "").upper()
        if elem_label:
            draw.text((40, 148), elem_label, font=self._pfont(14, 700), fill=accent, anchor="lm")
        self._draw_fit(draw, (38, 172), (c.name or "--").upper(),
                       max_width=320, size=44, weight=700, color=ivory)
        self._stars(draw, (40, 226), c.rarity or 0, size=18, color=gold)

        self._draw_constellations(base, draw, c, ctx.icons, theme)

        # Bottom-left level & friendship pill
        draw_glass((38, 636, 280, 674), radius=18, fill=(20, 18, 26, 230))
        draw.text((56, 655), f"Lv. {self._fmt(c.level)}  |  C{c.constellation}  |  Friendship {c.friendship}",
                  font=self._pfont(13, 600), fill=ivory, anchor="lm")
        if ctx.player and ctx.player.uid:
            draw.text((40, 694), f"UID: {ctx.player.uid}", font=self._pfont(12, 400),
                      fill=muted, anchor="lm")

        # -- top-right: floating weapon banner (x=540..1250, y=28..164) --
        draw_glass((540, 28, 1250, 164), radius=16)
        # Subtle elemental glow strip on the right of the weapon banner
        draw.rounded_rectangle((540, 28, 1250, 32), radius=2, fill=accent)
        if c.weapon:
            self._paste_icon(base, ctx.icons, c.weapon.icon, (1170, 96, 96), fit=True)
            self._stars(draw, (1170, 148), c.weapon.rarity or 0, size=12, color=gold, anchor="mm")
            self._draw_fit(draw, (564, 58), (c.weapon.name or "--").upper(),
                           max_width=520, size=22, weight=700, color=ivory, anchor="lm")
            draw.text((564, 88), f"Lv. {c.weapon.level} / {_weapon_max_level(c.weapon)}",
                      font=self._pfont(14, 600), fill=muted, anchor="lm")
            draw_glass((664, 75, 704, 101), radius=6, fill=(44, 38, 42, 255), border=accent)
            draw.text((684, 88), f"R{c.weapon.refinement}", font=self._pfont(13, 700), fill=gold, anchor="mm")

            px = 564
            if c.weapon.main_stat_value is not None:
                draw_glass((px, 114, px + 112, 144), radius=8, fill=(36, 34, 46, 240))
                draw.text((px + 56, 129), f"ATK {c.weapon.main_stat_value:,.0f}",
                          font=self._pfont(13, 600), fill=ivory, anchor="mm")
                px += 122
            if c.weapon.sub_stat_value is not None:
                draw_glass((px, 114, px + 118, 144), radius=8, fill=(36, 34, 46, 240))
                draw.text((px + 59, 129), _weapon_sub_text(c.weapon.sub_stat_name, c.weapon.sub_stat_value),
                          font=self._pfont(13, 600), fill=ivory, anchor="mm")

        # -- middle row: STATS (x=540..880) & TALENTS (x=896..1250), y=182..436 --
        draw_glass((540, 182, 880, 436), radius=16)
        draw.text((562, 204), "STATS", font=self._pfont(13, 700), fill=accent, anchor="lm")
        s = c.stats
        # Large HP highlight
        draw.text((562, 236), self._fmt(s.hp), font=self._pfont(26, 700), fill=ivory, anchor="lm")
        draw.text((666, 240), "HP", font=self._pfont(13, 600), fill=muted, anchor="lm")

        stat_rows = [
            ("ATK", self._fmt(s.atk)),
            ("DEF", self._fmt(s.defense)),
            ("EM", self._fmt(s.elemental_mastery)),
            ("CRIT RATE", self._fmt(s.crit_rate, percent=True)),
            ("CRIT DMG", self._fmt(s.crit_dmg, percent=True)),
            ("ER", self._fmt(s.energy_recharge, percent=True)),
            ("ELEM DMG", self._fmt(self._elemental_bonus(s, c.element), percent=True)),
        ]
        for idx, (label, val) in enumerate(stat_rows):
            ry = 274 + idx * 23
            if idx > 0:
                draw.line((562, ry - 11, 858, ry - 11), fill=divider_col, width=1)
            draw.text((562, ry), label, font=self._pfont(12, 600), fill=muted, anchor="lm")
            draw.text((858, ry), val, font=self._pfont(14, 700), fill=ivory, anchor="rm")

        # Right sub-panel: vertical TALENTS list
        draw_glass((896, 182, 1250, 436), radius=16)
        draw.text((918, 204), "TALENTS", font=self._pfont(13, 700), fill=accent, anchor="lm")
        talent_names = ("NORMAL ATTACK", "ELEMENTAL SKILL", "ELEMENTAL BURST")
        for idx, tal in enumerate((c.talents or [])[:3]):
            ty = 252 + idx * 64
            draw.ellipse((918, ty - 24, 966, ty + 24), fill=(38, 34, 48, 255), outline=accent, width=1)
            self._paste_icon(base, ctx.icons, tal.icon, (942, ty, 40), fit=True)
            draw.text((982, ty - 8), talent_names[idx] if idx < 3 else "TALENT",
                      font=self._pfont(12, 700), fill=ivory, anchor="lm")
            crown = tal.level >= 10
            draw.text((982, ty + 12), f"Lv. {tal.level}", font=self._pfont(13, 600),
                      fill=gold if crown else muted, anchor="lm")

        # -- bottom-right: unified ARTIFACTS glass panel (x=540..1250, y=454..696) --
        draw_glass((540, 454, 1250, 696), radius=16)
        draw.text((562, 476), "ARTIFACTS", font=self._pfont(13, 700), fill=accent, anchor="lm")
        set_name, set_count, _ = self._dominant_set(c.artifacts or [])
        if set_name:
            draw.text((1228, 476), f"{set_name} ({set_count}-pc)",
                      font=self._pfont(12, 600), fill=ivory, anchor="rm")

        by_slot = {a.slot.lower(): a for a in (c.artifacts or [])}
        col_w = 134
        for i, slot in enumerate(("flower", "plume", "sands", "goblet", "circlet")):
            cx = 558 + i * col_w + col_w // 2
            art = by_slot.get(slot)
            if art is None:
                draw.text((cx, 580), slot.upper(), font=self._pfont(11, 600), fill=muted, anchor="mm")
                continue
            self._paste_icon(base, ctx.icons, art.icon, (cx, 526, 56), fit=True)
            self._stars(draw, (cx, 562), art.rarity or 5, size=10, color=gold, anchor="mm")
            if art.main_stat:
                self._draw_fit(draw, (cx, 582), art.main_stat.name, max_width=124, size=11, color=muted, anchor="mm")
                self._draw_fit(draw, (cx, 600), _stat_value(art.main_stat, signed=False),
                               max_width=124, size=15, weight=700, color=ivory, anchor="mm")
            for j, sub in enumerate(art.sub_stats[:4]):
                sy = 622 + j * 17
                self._draw_fit(draw, (cx, sy), f"{sub.name} {_stat_value(sub, signed=True)}",
                               max_width=126, size=10, color=muted, anchor="mm")

        return self._to_png(base)

    @staticmethod
    def _dominant_set(artifacts):
        counts: dict[str, int] = {}
        icons: dict[str, str] = {}
        for a in artifacts:
            if a.set_name:
                counts[a.set_name] = counts.get(a.set_name, 0) + 1
                if a.icon and a.set_name not in icons:
                    icons[a.set_name] = a.icon
        if not counts:
            return None, 0, None
        name = max(counts, key=counts.get)
        return name, counts[name], icons.get(name)

    def _draw_ranking_badge(self, base, draw, ranking, accent) -> None:
        box = card_layout.RANKING_BADGE_BOX
        badge = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), (0, 0, 0, 0))
        bd = ImageDraw.Draw(badge)
        bd.rounded_rectangle([0, 0, badge.width - 1, badge.height - 1], radius=14,
                             fill=(20, 18, 24, 210), outline=(*accent, 255), width=2)
        base.alpha_composite(badge, (box[0], box[1]))
        cy = (box[1] + box[3]) // 2
        parts = []
        if ranking.rank is not None:
            parts.append((f"#{ranking.rank:,}", "RANK"))
        if ranking.top_percent is not None:
            parts.append((f"{ranking.top_percent:.1f}%", "TOP"))
        if ranking.calculation_name:
            parts.append((ranking.calculation_name, "CATEGORY"))
        n = max(1, len(parts))
        seg = (box[2] - box[0]) // n
        for i, (val, label) in enumerate(parts):
            cx = box[0] + seg * i + seg // 2
            draw.text((cx, cy - 10), val, font=self._pfont(22, 800), fill=(*accent, 255), anchor="mm")
            draw.text((cx, cy + 16), label, font=self._pfont(12, 500), fill=(200, 200, 210), anchor="mm")

    # -- cards -------------------------------------------------------------
    def render_character_card(self, ctx: CharacterCardContext) -> bytes:
        img, draw = self._canvas(ctx)
        lang = ctx.language
        c = ctx.character
        y = 40
        if c is None:
            self._text(draw, (40, y), t("error.character_not_found", lang), size=32)
            return self._to_png(img)

        # Artwork slot (placeholder-aware).
        art = self._assets.load("characters", c.art or c.icon or c.id or "unknown", size=(320, 320))
        img.alpha_composite(art, (40, 40))
        if ctx.frame:
            frame = self._assets.load("frames", ctx.frame, size=(320, 320))
            img.alpha_composite(frame, (40, 40))

        # Header text next to the artwork.
        x = 400
        y = self._text(draw, (x, 50), c.name, size=44)
        y = self._text(draw, (x, y), t("character.level", lang, level=c.level), size=28, color=_MUTED)
        y = self._text(draw, (x, y), t("character.constellation", lang, constellation=c.constellation),
                       size=28, color=_MUTED)
        if c.weapon:
            y = self._text(
                draw, (x, y),
                t("character.weapon", lang, name=c.weapon.name,
                  refinement=c.weapon.refinement, level=c.weapon.level),
                size=26, color=_MUTED,
            )

        # Stats panel.
        y = 400
        self._panel(draw, (40, y, 860, y + 300))
        y = self._text(draw, (60, y + 20), t("character.stats_title", lang), size=30)
        s = c.stats
        rows = [
            (t("stats.hp", lang), f"{s.hp:,.0f}"),
            (t("stats.atk", lang), f"{s.atk:,.0f}"),
            (t("stats.def", lang), f"{s.defense:,.0f}"),
            (t("stats.crit_rate", lang), f"{s.crit_rate:.1f}%"),
            (t("stats.crit_dmg", lang), f"{s.crit_dmg:.1f}%"),
            (t("stats.energy_recharge", lang), f"{s.energy_recharge:.1f}%"),
            (t("stats.elemental_mastery", lang), f"{s.elemental_mastery:,.0f}"),
        ]
        for label, value in rows:
            draw.text((60, y), label, font=self._font(24), fill=_MUTED)
            draw.text((520, y), value, font=self._font(24), fill=_TEXT)
            y += 34

        # Ranking panel (only if available).
        if c.ranking and c.ranking.available:
            ry = 730
            self._panel(draw, (40, ry, 860, ry + 180))
            ry = self._text(draw, (60, ry + 20), t("ranking.title", lang), size=30)
            if c.ranking.rank is not None:
                ry = self._text(draw, (60, ry), t("ranking.rank", lang, rank=c.ranking.rank), size=24, color=_MUTED)
            if c.ranking.top_percent is not None:
                ry = self._text(draw, (60, ry),
                                t("ranking.top_percent", lang, percent=f"{c.ranking.top_percent:.1f}"),
                                size=24, color=_MUTED)

        return self._to_png(img)

    def render_abyss_card(self, ctx: AbyssCardContext) -> bytes:
        img, draw = self._canvas(ctx)
        lang = ctx.language
        title = t("abyss.pre_title" if (ctx.abyss and ctx.abyss.is_previous) else "abyss.title", lang)
        y = self._text(draw, (40, 40), _strip_tags(title), size=40)
        if not ctx.abyss or not ctx.abyss.available:
            self._text(draw, (40, y), t("abyss.unavailable", lang), size=28, color=_MUTED)
            return self._to_png(img)
        a = ctx.abyss
        self._panel(draw, (40, y, 860, y + 220))
        yy = y + 20
        if a.max_floor:
            yy = self._text(draw, (60, yy), t("abyss.max_floor", lang, floor=a.max_floor), size=28)
        if a.total_stars is not None:
            yy = self._text(draw, (60, yy), t("abyss.stars", lang, stars=a.total_stars), size=28)
        return self._to_png(img)

    def render_theater_card(self, ctx: TheaterCardContext) -> bytes:
        img, draw = self._canvas(ctx)
        lang = ctx.language
        y = self._text(draw, (40, 40), _strip_tags(t("theater.title", lang)), size=40)
        if not ctx.theater or not ctx.theater.available:
            self._text(draw, (40, y), t("theater.unavailable", lang), size=28, color=_MUTED)
            return self._to_png(img)
        th = ctx.theater
        self._panel(draw, (40, y, 860, y + 220))
        yy = y + 20
        if th.difficulty:
            yy = self._text(draw, (60, yy), th.difficulty, size=28)
        if th.act is not None:
            yy = self._text(draw, (60, yy), t("theater.act", lang, act=th.act), size=28)
        if th.stars is not None:
            yy = self._text(draw, (60, yy), t("abyss.stars", lang, stars=th.stars), size=28)
        return self._to_png(img)


def _strip_tags(text: str) -> str:
    """Remove simple HTML tags so titles render cleanly on an image."""
    import re

    return re.sub(r"<[^>]+>", "", text)
