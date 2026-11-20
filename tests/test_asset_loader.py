"""Tests for the dynamic asset loader and placeholder fallback."""

from __future__ import annotations

from PIL import Image

from bot.assets.loader import AssetLoader


def test_missing_asset_returns_placeholder_image(tmp_path):
    loader = AssetLoader(root=tmp_path)  # empty dir -> nothing resolves
    img = loader.load("characters", "does_not_exist")
    assert isinstance(img, Image.Image)
    assert img.size == (256, 256)


def test_resolve_finds_existing_file(tmp_path):
    (tmp_path / "icons").mkdir()
    icon = tmp_path / "icons" / "sword.png"
    Image.new("RGBA", (10, 10)).save(icon)

    loader = AssetLoader(root=tmp_path)
    # Resolves with or without an explicit extension.
    assert loader.resolve("icons", "sword.png") == icon
    assert loader.resolve("icons", "sword") == icon
    assert loader.resolve("icons", "missing") is None


def test_resolve_handles_dotted_stem(tmp_path):
    # A key whose stem contains a dot (e.g. "char_1.2") must not have its
    # trailing segment mistaken for an extension and stripped away.
    (tmp_path / "characters").mkdir()
    asset = tmp_path / "characters" / "char_1.2.png"
    Image.new("RGBA", (10, 10)).save(asset)

    loader = AssetLoader(root=tmp_path)
    assert loader.resolve("characters", "char_1.2") == asset
    assert loader.resolve("characters", "char_1.2.png") == asset


def test_load_resizes(tmp_path):
    (tmp_path / "backgrounds").mkdir()
    Image.new("RGBA", (50, 50)).save(tmp_path / "backgrounds" / "bg.png")
    loader = AssetLoader(root=tmp_path)
    img = loader.load("backgrounds", "bg", size=(100, 120))
    assert img.size == (100, 120)


def test_uses_placeholder_file_when_present(tmp_path):
    (tmp_path / "placeholders").mkdir()
    Image.new("RGBA", (64, 64), (1, 2, 3, 255)).save(tmp_path / "placeholders" / "default.png")
    loader = AssetLoader(root=tmp_path)
    img = loader.load("frames", "nope")
    assert isinstance(img, Image.Image)
