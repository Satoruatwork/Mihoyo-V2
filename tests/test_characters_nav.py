"""Integration tests for the single-message /mycharacters navigation.

Verify the behaviors required by the callback-flow fix:
  * the callback query is answered FIRST (before any data work);
  * clicking a character EDITS the message media (no new message);
  * Back edits the media back to the banner; paging edits only the caption;
  * rendered card images are reused by file_id (no second render).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.app_context import BOT_DATA_KEY
from bot.commands import characters
from bot.models.character import Character
from bot.models.player import PlayerInfo, Showcase
from bot.utils import callbacks


@pytest.fixture
def new_renders(monkeypatch):
    """Counts calls to the production (slot-driven) renderer."""

    class _Counter:
        count = 0

    counter = _Counter()

    class _Stub:
        def render(self, data, *, debug=False):
            counter.count += 1
            return b"PNGDATA"

    monkeypatch.setattr(characters, "get_card_renderer", lambda: _Stub())
    return counter


@pytest.fixture(autouse=True)
def _clear_cache():
    characters._FILE_IDS._data.clear()
    yield
    characters._FILE_IDS._data.clear()


class _FakeShowcaseService:
    def __init__(self, showcase: Showcase) -> None:
        self._s = showcase

    async def get_showcase(self, uid: str, lang: str = "en") -> Showcase:
        return self._s


class _FakeAccount:
    async def get_uid(self, tid):
        return "901211014"


class _FakeArtwork:
    async def get_portrait(self, character):
        return None

    async def get_images(self, urls):
        return {}


class _CountingRenderer:
    def __init__(self):
        self.renders = 0

    def render_profile_card(self, ctx):
        self.renders += 1
        return b"PNGDATA"


class _FakeMessage:
    """A photo message that records reply_photo (should NOT be used for navigation)."""

    def __init__(self):
        self.photo = [SimpleNamespace(file_id="banner_fid")]
        self.reply_photo_calls = 0

    async def reply_photo(self, **kwargs):
        self.reply_photo_calls += 1
        return _FakeMessage()


class _FakeQuery:
    def __init__(self, data: str):
        self.data = data
        self.from_user = SimpleNamespace(id=42)
        self.message = _FakeMessage()
        self.events: list[str] = []

    async def answer(self, text=None, show_alert=False):
        self.events.append("answer")

    async def edit_message_media(self, media, reply_markup=None):
        self.events.append("edit_media")
        self.last_caption = getattr(media, "caption", None)
        return SimpleNamespace(photo=[SimpleNamespace(file_id="card_fid")])

    async def edit_message_caption(self, caption=None, parse_mode=None, reply_markup=None):
        self.events.append("edit_caption")

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        self.events.append("edit_text")


def _make_app(renderer):
    showcase = Showcase(
        player=PlayerInfo(uid="901211014", nickname="Wanderer"),
        characters=[Character(id="10000046", name="Furina", level=90, constellation=1)],
    )
    return SimpleNamespace(
        settings=SimpleNamespace(default_language="en", assets_path=__import__("pathlib").Path("/nonexistent")),
        account_service=_FakeAccount(),
        character_service=_FakeShowcaseService(showcase),
        artwork_service=_FakeArtwork(),
        renderer=renderer,
        language_for=_lang_for,
    )


async def _lang_for(uid):
    return "en"


def _make_ctx(app):
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={BOT_DATA_KEY: app}),
        user_data={},
    )
    return context


def _make_update(query):
    return SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=42))


async def test_click_character_edits_media_no_new_message(new_renders):
    renderer = _CountingRenderer()
    app = _make_app(renderer)
    ctx = _make_ctx(app)
    data = callbacks.encode(callbacks.ACTION_CHAR, uid="901211014", char_id="10000046", page=0, owner=42)
    query = _FakeQuery(data)

    await characters.on_callback(_make_update(query), ctx)

    assert query.events[0] == "answer"          # answered FIRST
    assert "edit_media" in query.events          # edited in place
    assert query.message.reply_photo_calls == 0  # NO new message
    # The production path now goes through the slot-driven CharacterCardRenderer, so the
    # legacy renderer must NOT be touched — that is what proves the wiring took effect.
    assert renderer.renders == 0, "legacy renderer must not serve normal requests"
    assert new_renders.count == 1


async def test_reopening_character_reuses_image_no_rerender(new_renders):
    renderer = _CountingRenderer()
    app = _make_app(renderer)
    ctx = _make_ctx(app)
    data = callbacks.encode(callbacks.ACTION_CHAR, uid="901211014", char_id="10000046", page=0, owner=42)

    await characters.on_callback(_make_update(_FakeQuery(data)), ctx)
    await characters.on_callback(_make_update(_FakeQuery(data)), ctx)

    assert new_renders.count == 1  # second open served from the file_id cache
    assert renderer.renders == 0


async def test_back_edits_media_to_banner():
    app = _make_app(_CountingRenderer())
    ctx = _make_ctx(app)
    data = callbacks.encode(callbacks.ACTION_BACK, uid="901211014", page=0, owner=42)
    query = _FakeQuery(data)

    await characters.on_callback(_make_update(query), ctx)

    assert query.events[0] == "answer"
    assert "edit_media" in query.events  # swapped back to the banner in place


async def test_paging_edits_caption_only():
    # Two pages worth of characters so pagination applies.
    chars = [Character(id=str(10000000 + i), name=f"C{i}", level=90) for i in range(10)]
    app = _make_app(_CountingRenderer())
    app.character_service = _FakeShowcaseService(
        Showcase(player=PlayerInfo(uid="901211014"), characters=chars)
    )
    ctx = _make_ctx(app)
    data = callbacks.encode(callbacks.ACTION_PAGE, uid="901211014", page=1, owner=42)
    query = _FakeQuery(data)

    await characters.on_callback(_make_update(query), ctx)

    assert "edit_caption" in query.events   # cheapest edit for same-banner paging
    assert "edit_media" not in query.events
