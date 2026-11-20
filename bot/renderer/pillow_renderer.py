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

    def _template_base(self) -> Image.Image:
        """Return a fresh copy of the card template, decoded+resized only once.

        The template is a static asset; decoding and resizing it on every render was a
        repeated disk read + JPEG decode. We cache the prepared RGBA image in memory and
        return a ``.copy()`` so each render can safely composite onto its own canvas.
        """
        cached = getattr(self, "_template_cache", None)
        if cached is None:
            try:
                base = Image.open(bootstrap.template_path()).convert("RGBA")
                if base.size != card_layout.CARD_SIZE:
                    base = base.resize(card_layout.CARD_SIZE)
            except Exception as exc:  # noqa: BLE001 - template missing -> minimal fallback
                logger.warning("Card template missing (%s); using flat canvas", exc)
                base = Image.new("RGBA", card_layout.CARD_SIZE, (32, 30, 40, 255))
            cached = base
            self._template_cache = cached
        return cached.copy()

    def render_profile_card(self, ctx: CharacterCardContext) -> bytes:
        c = ctx.character
        theme = card_layout.theme_for(c.element if c else None)

        # Base canvas: the cached template (decoded once). Fallback handled in the helper.
        base = self._template_base()

        # No full-card element tint. It used to wash the entire template in the element
        # colour at alpha 60, which shifted the cream panels well off the approved design
        # (measured against the reference: cream (239,231,220) came out as (222,188,178), a
        # clear pink cast on a Pyro character). The element still drives the portrait glow
        # and the accent colour below, which is where the reference actually uses it.

        # Portrait (glow backdrop + cover-fit art) into the oval frame.
        portrait = ctx.portrait if isinstance(ctx.portrait, Image.Image) else None
        self._fit_portrait_ellipse(base, portrait, card_layout.PORTRAIT_BOX, theme["glow"])

        draw = ImageDraw.Draw(base)
        if c is None:
            return self._to_png(base)

        accent = theme["accent"]
        dark = (52, 44, 34)

        # Erase the template's baked placeholder text/stars before drawing live values, by
        # filling each region with its local panel colour (sampled adjacent to the text) so
        # nothing ghosts through. Panels differ (dark top bar vs cream body), so sample per area.
        def sample(x, y):
            return base.getpixel((x, y))[:3]

        def mask(box, color):
            draw.rectangle(box, fill=color)

        cream = sample(1000, 92)          # artifact / cream body panels
        wcream_top = sample(690, 150)     # weapon panel cream near name/type boxes
        wcream_bot = sample(470, 245)     # weapon panel cream near the rarity stars
        header_bg = sample(330, 20)       # header marble
        topbar = sample(500, 60)          # dark top-bar interior (not its lighter edge)
        setcream = sample(760, 522)       # set-bonus panel cream (right of "SET NAME")
        lvbox = sample(650, 213)          # weapon "Lv." box interior
        self._cream = cream               # reused by talent/artifact/set erases

        # -- header --
        mask((110, 24, 362, 70), header_bg)       # CHARACTER NAME
        mask((116, 70, 250, 92), header_bg)       # header rarity stars
        mask((116, 88, 322, 110), header_bg)      # Title / Nickname
        # -- top bar (dark): level "/" and baked rarity stars --
        mask((428, 50, 476, 80), topbar)
        mask((724, 52, 826, 80), topbar)
        # -- weapon panel --
        mask((512, 128, 704, 160), wcream_top)    # WEAPON NAME
        mask((398, 215, 494, 239), wcream_bot)    # baked rarity stars under the icon
        # The second stat box is NOT unused — it holds the weapon's secondary stat, so its
        # baked frame is kept and only the placeholder glyph inside it is cleared.
        mask((668, 164, 758, 189), wcream_top)    # 2nd stat box interior
        mask((806, 166, 832, 189), wcream_top)    # "R" box interior (cream, as in the reference)
        mask((508, 201, 700, 226), lvbox)         # baked "Lv. /"
        # -- set bonus: SET NAME (wide enough to also clear the leading 'S') --
        mask((608, 510, 762, 542), setcream)
        # -- artifacts: main stat, baked stars, substats per card --
        for i, top in enumerate(card_layout.ARTIFACT_CARD_TOP):
            dy = top - card_layout.ARTIFACT_CARD_REF_TOP
            mask((968, 94 + dy, 1086, 136 + dy), cream)           # Main Stat (name + value lines)
            mask((896, 140 + dy, 968, 162 + dy), cream)           # baked rarity stars
            for sy in card_layout.ARTIFACT_SUBSTAT_YS:
                mask((1096, sy - 10 + dy, 1262, sy + 12 + dy), cream)  # Substats
        # -- talent panel: baked "/" values under each icon --
        talcream = sample(405, 548)
        for tx, ty in card_layout.TALENT_LEVEL_POS:
            mask((tx - 16, ty - 13, tx + 16, ty + 11), talcream)

        # -- header --
        # weight 600, not 800: the reference's name is a lighter display face, and 800 read
        # as noticeably heavier than the approved card at the same cap height.
        self._draw_fit(draw, card_layout.NAME_POS, (c.name or "--").upper(),
                       max_width=card_layout.NAME_MAX_WIDTH, size=42, weight=600, color=dark)
        self._stars(draw, card_layout.RARITY_STARS_POS, c.rarity or 0, size=20)
        # The template's "Title / Nickname" line is intentionally left blank: the card shows
        # character names only. It previously drew the *player's* nickname here, which
        # mislabelled the slot (it is a character field, not an account one). The baked
        # placeholder is already erased by the mask above, so nothing is drawn.

        # -- top bar: level / constellation / rarity --
        draw.text(card_layout.LEVEL_VALUE_POS, self._fmt(c.level), font=self._pfont(22, 600),
                  fill=(240, 232, 214), anchor="mm")
        draw.text(card_layout.CONSTELLATION_VALUE_POS, str(c.constellation),
                  font=self._pfont(20, 700), fill=(240, 232, 214), anchor="mm")
        self._stars(draw, card_layout.RARITY_BAR_STARS_POS, c.rarity or 0, size=18, anchor="mm")

        # -- constellation rail (real lock state, dynamic icons) --
        self._draw_constellations(base, draw, c, ctx.icons, theme)

        # -- weapon (icon + rarity stars + name + level + refinement + type) --
        if c.weapon:
            self._paste_icon(base, ctx.icons, c.weapon.icon, card_layout.WEAPON_ICON_BOX,
                             fit=True, erase=wcream_bot)
            self._draw_fit(draw, card_layout.WEAPON_NAME_POS, c.weapon.name or "--",
                           max_width=card_layout.WEAPON_NAME_MAX_WIDTH, size=19, weight=600, color=dark)
            self._stars(draw, (card_layout.WEAPON_ICON_BOX[0], 226),
                        c.weapon.rarity or 0, size=13, anchor="mm")
            # The template's two boxes hold the weapon's STATS (base ATK, then its secondary
            # stat) — that is what the reference shows. This used to print the weapon class
            # ("Polearm") in the first box and leave the second empty, discarding both values.
            if c.weapon.main_stat_value is not None:
                draw.text(card_layout.WEAPON_MAIN_STAT_POS, f"{c.weapon.main_stat_value:,.0f}",
                          font=self._pfont(17, 600), fill=dark, anchor="lm")
            if c.weapon.sub_stat_value is not None:
                draw.text(card_layout.WEAPON_SUB_STAT_POS,
                          _weapon_sub_text(c.weapon.sub_stat_name, c.weapon.sub_stat_value),
                          font=self._pfont(17, 600), fill=dark, anchor="lm")
            # "Lv. 90 / 90" — the template bakes the separator, so both numbers are drawn.
            draw.text(card_layout.WEAPON_LEVEL_POS,
                      f"Lv. {c.weapon.level} / {_weapon_max_level(c.weapon)}",
                      font=self._pfont(18), fill=dark, anchor="lm")
            # Dark text on the cream box, matching the reference (was light-on-dark).
            draw.text(card_layout.WEAPON_REFINE_POS, f"R{c.weapon.refinement}",
                      font=self._pfont(17, 700), fill=dark, anchor="mm")

        # -- talent icons (erase the baked emblem first, then the transparent PNG icon) --
        for box, tal in zip(card_layout.TALENT_ICON_BOXES, (c.talents or [])[:3]):
            self._paste_icon(base, ctx.icons, tal.icon, box, fit=True, erase=talcream)

        # -- base stats (values right-aligned per labelled row) --
        s = c.stats
        stat_values = {
            "hp": self._fmt(s.hp), "atk": self._fmt(s.atk), "defense": self._fmt(s.defense),
            "elemental_mastery": self._fmt(s.elemental_mastery),
            "crit_rate": self._fmt(s.crit_rate, percent=True),
            "crit_dmg": self._fmt(s.crit_dmg, percent=True),
            "energy_recharge": self._fmt(s.energy_recharge, percent=True),
            "elemental_bonus": self._fmt(self._elemental_bonus(s, c.element), percent=True),
        }
        for field, y in card_layout.BASE_STAT_ROWS_Y.items():
            draw.text((card_layout.BASE_STAT_VALUE_X, y), stat_values.get(field, "--"),
                      font=self._pfont(18, 600), fill=dark, anchor="rm")

        # -- talents --
        for pos, tal in zip(card_layout.TALENT_LEVEL_POS, (c.talents or [])[:3]):
            crown = tal.level >= 10
            draw.text(pos, str(tal.level), font=self._pfont(18, 700),
                      fill=(214, 168, 74) if crown else dark, anchor="mm")

        # -- artifacts (place each by slot) --
        by_slot = {a.slot.lower(): a for a in (c.artifacts or [])}
        for i, slot in enumerate(("flower", "plume", "sands", "goblet", "circlet")):
            art = by_slot.get(slot)
            if art is None:
                continue
            dy = card_layout.ARTIFACT_CARD_TOP[i] - card_layout.ARTIFACT_CARD_REF_TOP
            self._paste_icon(base, ctx.icons, art.icon, card_layout.ARTIFACT_ICON_BOXES[i],
                             fit=True, erase=cream)
            if art.main_stat:
                # Two lines, as in the reference: stat name above, formatted value below.
                nx, ny = card_layout.ARTIFACT_MAIN_NAME_POS
                vx, vy = card_layout.ARTIFACT_MAIN_VALUE_POS
                self._draw_fit(draw, (nx, ny + dy), art.main_stat.name,
                               max_width=card_layout.ARTIFACT_MAIN_MAX_WIDTH,
                               size=13, color=(90, 78, 62), anchor="lm")
                self._draw_fit(draw, (vx, vy + dy), _stat_value(art.main_stat, signed=False),
                               max_width=card_layout.ARTIFACT_MAIN_MAX_WIDTH,
                               size=17, weight=600, color=dark, anchor="lm")
            self._stars(draw, (card_layout.ARTIFACT_STARS_POS[0], card_layout.ARTIFACT_STARS_POS[1] + dy),
                        art.rarity or 5, size=13)
            for sub, sy in zip(art.sub_stats[:4], card_layout.ARTIFACT_SUBSTAT_YS):
                # Name and value are separate left-aligned columns, so a long name can never
                # push its value out of line with the rows above and below it.
                self._draw_fit(draw, (card_layout.ARTIFACT_SUBSTAT_X, sy + dy), sub.name,
                               max_width=card_layout.ARTIFACT_SUBSTAT_NAME_MAX_WIDTH,
                               size=13, color=(90, 78, 62), anchor="lm")
                self._draw_fit(draw, (card_layout.ARTIFACT_SUBSTAT_VALUE_X, sy + dy),
                               _stat_value(sub, signed=True),
                               max_width=card_layout.ARTIFACT_SUBSTAT_VALUE_MAX_WIDTH,
                               size=13, weight=600, color=dark, anchor="lm")

        # -- set bonus (dominant set from equipped artifacts) + set icon --
        set_name, set_count, set_icon = self._dominant_set(c.artifacts or [])
        if set_name:
            self._draw_fit(draw, card_layout.SET_NAME_POS, f"{set_name} ({set_count})",
                           max_width=150, size=16, weight=700, color=dark, anchor="lm")
        if set_icon:
            self._paste_icon(base, ctx.icons, set_icon, card_layout.SET_ICON_BOX,
                             fit=True, erase=setcream)

        # -- bottom summary bar --
        bottom_vals = [
            self._fmt(s.crit_rate, percent=True), self._fmt(s.crit_dmg, percent=True),
            self._fmt(s.energy_recharge, percent=True), self._fmt(s.atk), self._fmt(s.defense),
            self._fmt(s.elemental_mastery),
            self._fmt(self._elemental_bonus(s, c.element), percent=True),
        ]
        for x, val in zip(card_layout.BOTTOM_BAR_VALUE_X, bottom_vals):
            draw.text((x, card_layout.BOTTOM_BAR_Y), val, font=self._pfont(15, 600),
                      fill=(228, 220, 205), anchor="mm")

        # Akasha ranking is intentionally NOT drawn on the image — it lives only in the
        # Telegram caption, keeping the card visually clean.
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
