"""``/myc`` must be an alias of ``/mycharacters`` — one handler, one pipeline, one output.

These tests assert the *structural* guarantee (both command names are bound to the same
callable, so they cannot drift) as well as the observable one (running the flow produces
identical text and buttons regardless of which name was typed).
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from telegram.ext import CommandHandler

from bot.app_context import BOT_DATA_KEY
from bot.commands import characters
from bot.main import _register_handlers, _set_bot_commands
from bot.models.character import Character
from bot.models.player import PlayerInfo, Showcase


class _RecordingApplication:
    """Captures handlers registered by ``_register_handlers``."""

    def __init__(self) -> None:
        self.handlers: list[object] = []

    def add_handler(self, handler, group=0):
        self.handlers.append(handler)

    def add_error_handler(self, handler):
        pass


def _command_handlers():
    app = _RecordingApplication()
    _register_handlers(app)
    return [h for h in app.handlers if isinstance(h, CommandHandler)]


def test_both_command_names_are_bound_to_one_handler():
    """The canonical requirement: /mycharacters and /myc share a single registration."""
    owners = [h for h in _command_handlers() if {"mycharacters", "myc"} & set(h.commands)]

    assert len(owners) == 1, "/myc must not have its own handler registration"
    handler = owners[0]
    assert set(handler.commands) == {"mycharacters", "myc"}
    assert handler.callback is characters.my_characters


def test_no_separate_myc_implementation_exists():
    """Guards against a future 'my_c'/'myc_command' duplicate creeping back in."""
    duplicates = [
        name
        for name, obj in vars(characters).items()
        if inspect.isfunction(obj) and "myc" in name.lower().replace("_", "")
        and name != "my_characters"
    ]
    assert duplicates == [], f"duplicate /myc implementations: {duplicates}"


async def test_published_command_menu_lists_both_names():
    published: list[list[tuple[str, str]]] = []

    class _Bot:
        async def set_my_commands(self, commands):
            published.append(commands)

    await _set_bot_commands(SimpleNamespace(bot=_Bot()))

    names = {name for name, _ in published[0]}
    assert {"mycharacters", "myc"} <= names


# --------------------------------------------------------------------------- behavioural parity
class _FakeAccount:
    async def require_uid(self, tid):
        return "901211014"

    async def get_uid(self, tid):
        return "901211014"


class _FakeCharacterService:
    def __init__(self, showcase):
        self._s = showcase
        self.calls = 0

    async def get_showcase(self, uid, lang="en"):
        self.calls += 1
        return self._s


class _CapturingMessage:
    def __init__(self):
        self.sent: list[dict] = []

    async def reply_photo(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(photo=[SimpleNamespace(file_id="fid")])


def _app_and_update():
    import pathlib

    showcase = Showcase(
        player=PlayerInfo(uid="901211014", nickname="Rexxyyy"),
        # A character that exists in no local list — the pipeline is name-agnostic.
        characters=[Character(id="10000150", name="Odette", level=90, constellation=0)],
    )
    app = SimpleNamespace(
        settings=SimpleNamespace(default_language="en", assets_path=pathlib.Path("/nonexistent")),
        account_service=_FakeAccount(),
        character_service=_FakeCharacterService(showcase),
        language_for=_lang_for,
    )
    message = _CapturingMessage()
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=42),
        callback_query=None,
    )
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={BOT_DATA_KEY: app}),
        bot=SimpleNamespace(send_chat_action=_noop),
        user_data={},
        args=[],
    )
    return app, update, context, message


async def _lang_for(uid):
    return "en"


async def _noop(**kwargs):
    return None


async def test_myc_and_mycharacters_produce_identical_output():
    """Same handler, so invoking it twice (as either name would) yields the same card."""
    results = []
    for _ in range(2):
        _app, update, context, message = _app_and_update()
        await characters.my_characters(update, context)
        sent = message.sent[0]
        results.append((sent["caption"], sent["reply_markup"].to_dict()))

    assert results[0] == results[1]
    assert "Odette" in results[0][1]["inline_keyboard"][0][0]["text"]


async def test_new_character_is_listed_without_any_local_entry():
    """A character absent from every local file still appears with level + constellation."""
    _app, update, context, message = _app_and_update()

    await characters.my_characters(update, context)

    button = message.sent[0]["reply_markup"].to_dict()["inline_keyboard"][0][0]
    assert button["text"] == "Odette (Lv.90 C0)"
    assert "10000150" in button["callback_data"]
