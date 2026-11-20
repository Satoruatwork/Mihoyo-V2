"""Offline demo of the layer-based rendering engine.

Renders the bundled ``profile.json`` layout to a PNG with no network and no bundled art —
missing assets fall back to placeholders, so you can see the *layer composition* (panels,
splash slot, icon rows, dynamic text, footer) working end to end. Drop real images into the
asset folders and the same layout renders the finished card, no code change.

    python -m example.layered_demo            # writes layered_profile.png (1500px wide)
"""

from __future__ import annotations

from pathlib import Path

from enkarender.layered import LayeredAssetManager, LayeredRenderer, load_layout

HERE = Path(__file__).resolve().parent
LAYOUT = Path(__file__).resolve().parents[1] / "enkarender" / "layered" / "layouts" / "profile.json"

# The data that binds to the layout (text templates + asset names per layer).
DATA = {
    "background": "bg_hydro",
    "overlay": "sparkle",
    "portrait_frame": "frame_5star",
    "character_art": "furina",
    "element_icon": "Hydro",
    "weapon_icon": "splendor",
    "nickname": "Wanderer",
    "uid": "800000001",
    "level": 60,
    "world_level": 8,
    "char_name": "Furina",
    "char_level": 90,
    "constellation": 1,
    "weapon_name": "Splendor of Tranquil Waters",
    "refinement": 1,
    "artifacts": ["flower", "plume", "sands", "goblet", "circlet"],
    "talents": ["skill_na", "skill_e", "skill_q"],
    "stats": [
        {"icon": "hp", "value": "18,500"},
        {"icon": "atk", "value": "2,100"},
        {"icon": "crit_rate", "value": "72.4%"},
        {"icon": "crit_dmg", "value": "168.2%"},
        {"icon": "er", "value": "126.4%"},
    ],
    "footer": "Rendered by enkarender • layered engine",
}


def main() -> None:
    assets = LayeredAssetManager(HERE / "assets")  # empty dir -> placeholders
    engine = LayeredRenderer(assets)
    layout = load_layout(LAYOUT)

    png = engine.render_png(layout, DATA, target_width=1500)  # scale 1.5x from base 1000
    (HERE / "layered_profile.png").write_bytes(png)
    print(f"Wrote layered_profile.png ({len(png) // 1024} KB), {len(layout.layers)} layers")


if __name__ == "__main__":
    main()
