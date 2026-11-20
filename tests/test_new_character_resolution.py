"""Regression tests for newly released characters (the Odette failure).

The bug: enka.py downloads its game metadata once and never refreshes it. When Enka.Network
returns a character released after that download, ``GenshinClient._post_process_character``
can't find the id, logs to a logger the library disables by default, and returns early — so
the character arrives with an empty name, ``Element.NONE``, rarity 0 and a blank icon, and
the card renders an unidentified build.

These tests reproduce that shape without any network access:

* ``_FakeLibraryClient`` mimics enka.py exactly — including the early return on a missing id
  and the fact that ``update_assets()`` is what makes the character resolvable.
* No character is hardcoded anywhere: the "new" character is only known to the *upstream*
  metadata, exactly as a real new release would be.
"""

from __future__ import annotations

import pytest

from bot.api.character_metadata import (
    CharacterMeta,
    CharacterMetadataResolver,
    placeholder_name,
)
from bot.api.enka_assets import EnkaAssetRefresher
from bot.api.enka_client import EnkaClient
from bot.utils.errors import ApiUnavailable

# A character id that exists in no source file in this repository — the point being that
# nothing had to be added for it to work.
NEW_ID = 10000150
NEW_NAME = "Odette"
KNOWN_ID = 10000046
KNOWN_NAME = "Hu Tao"


# --------------------------------------------------------------------------- library doubles
class _Icon:
    """Mirrors enka.py's Icon: URLs are string substitutions on the side-icon path.

    An empty path still yields a syntactically valid URL ('https://enka.network/ui/.png'),
    which is precisely the trap the real model falls into for an unresolved character.
    """

    def __init__(self, side_icon_ui_path: str) -> None:
        self.side_icon_ui_path = side_icon_ui_path

    @property
    def side(self) -> str:
        return f"https://enka.network/ui/{self.side_icon_ui_path}.png"

    @property
    def front(self) -> str:
        return self.side.replace("Side_", "")

    @property
    def circle(self) -> str:
        return self.front.replace(".png", "_Circle.png")

    @property
    def gacha(self) -> str:
        return self.side.replace("AvatarIcon_Side", "Gacha_AvatarImg")


class _Element:
    """Stand-in for enka.py's ``Element`` StrEnum (``NONE`` stringifies to 'None')."""

    def __init__(self, value: str) -> None:
        self.value = value

    def __str__(self) -> str:
        return self.value


class _LibCharacter:
    """A character as enka.py's model would present it after post-processing (or not)."""

    def __init__(self, char_id: int, *, resolved: bool, name: str = "") -> None:
        self.id = char_id
        self.level = 90
        self.ascension = 6
        self.friendship_level = 10
        self.talents = []
        self.constellations = []
        self.artifacts = []
        self.stats = {}
        self.weapon = None
        if resolved:
            self.name = name
            self.element = _Element("Ice")
            self.rarity = 5
            self.icon = _Icon(f"UI_AvatarIcon_Side_{name}")
        else:
            # Exactly the state enka.py leaves behind when the id is missing from metadata.
            self.name = ""
            self.element = _Element("None")
            self.rarity = 0
            self.icon = _Icon("")


class _LibPlayer:
    nickname = "Rexxyyy"
    level = 60
    world_level = 8
    signature = ""


class _LibShowcase:
    def __init__(self, characters):
        self.player = _LibPlayer()
        self.characters = characters


class _FakeLibraryClient:
    """Behaves like ``enka.GenshinClient``: metadata coverage decides what resolves.

    ``known_ids`` is the stale on-disk metadata; ``update_assets()`` widens it to
    ``upstream_ids``, mirroring the real ``update_assets()`` re-download.
    """

    def __init__(self, payload_ids, known_ids, upstream_ids, *, names):
        self.payload_ids = payload_ids
        self.known_ids = set(known_ids)
        self.upstream_ids = set(upstream_ids)
        self.names = names
        self.update_calls = 0
        self.parse_calls = 0
        self.started = False
        self.closed = False
        self.lang = "en"

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def update_assets(self) -> None:
        self.update_calls += 1
        self.known_ids = set(self.upstream_ids)

    async def fetch_showcase(self, uid, *, info_only=False, raw=False):
        assert raw, "the bot must fetch raw so it can re-parse without a second request"
        return {
            "playerInfo": {"nickname": "Rexxyyy"},
            "avatarInfoList": [{"avatarId": i} for i in self.payload_ids],
            "uid": str(uid),
            "ttl": 60,
        }

    def parse_showcase(self, payload):
        self.parse_calls += 1
        characters = []
        for raw_char in payload.get("avatarInfoList", []):
            char_id = raw_char["avatarId"]
            resolved = char_id in self.known_ids
            characters.append(
                _LibCharacter(char_id, resolved=resolved, name=self.names.get(char_id, ""))
            )
        return _LibShowcase(characters)


class _FakeEnkaModule:
    """Minimal stand-in for the ``enka`` package, wired to one fake client."""

    def __init__(self, client) -> None:
        self._client = client

        class _Language:
            ENGLISH = "en"

        class _Gi:
            Language = _Language

        self.gi = _Gi()

    def GenshinClient(self, lang):  # noqa: N802 - mirrors the library's class name
        self._client.lang = lang
        return self._client


@pytest.fixture
def patch_enka(monkeypatch):
    """Install a fake ``enka`` module plus fresh (test-local) singletons."""

    def _install(client, *, refresher=None, resolver=None):
        import sys

        monkeypatch.setitem(sys.modules, "enka", _FakeEnkaModule(client))
        monkeypatch.setattr(
            "bot.api.enka_client.get_asset_refresher",
            lambda: refresher or EnkaAssetRefresher(ttl=10_000, force_cooldown=0),
        )
        monkeypatch.setattr(
            "bot.api.enka_client.get_metadata_resolver",
            lambda: resolver or CharacterMetadataResolver(),
        )

    return _install


# --------------------------------------------------------------------------- the actual bug
async def test_stale_metadata_is_refreshed_so_a_new_character_resolves(patch_enka):
    """The headline case: a character missing from stale metadata resolves after a refresh.

    Nothing about the character is hardcoded — it becomes resolvable purely because the
    metadata was updated, which is what happens for every future release.
    """
    client = _FakeLibraryClient(
        payload_ids=[KNOWN_ID, NEW_ID],
        known_ids=[KNOWN_ID],                      # stale: predates the new character
        upstream_ids=[KNOWN_ID, NEW_ID],           # upstream has published it
        names={KNOWN_ID: KNOWN_NAME, NEW_ID: NEW_NAME},
    )
    patch_enka(client)

    showcase = await EnkaClient().fetch_showcase("901211014")

    names = {c.id: c.name for c in showcase.characters}
    assert names[str(NEW_ID)] == NEW_NAME
    assert names[str(KNOWN_ID)] == KNOWN_NAME
    assert client.update_calls == 1, "the unresolved id must trigger exactly one refresh"


async def test_refresh_reparses_without_a_second_api_request(patch_enka):
    """Recovery must re-parse the payload already in hand, not re-hit Enka.Network."""
    calls = []
    client = _FakeLibraryClient(
        payload_ids=[NEW_ID], known_ids=[], upstream_ids=[NEW_ID], names={NEW_ID: NEW_NAME}
    )
    original = client.fetch_showcase

    async def counting(uid, *, info_only=False, raw=False):
        calls.append(uid)
        return await original(uid, info_only=info_only, raw=raw)

    client.fetch_showcase = counting
    patch_enka(client)

    await EnkaClient().fetch_showcase("901211014")

    assert len(calls) == 1, "only one showcase request may be made"
    assert client.parse_calls == 2, "the same payload is parsed again after the refresh"


async def test_new_character_survives_when_upstream_has_no_metadata_yet(patch_enka):
    """Enka hasn't published the id yet: log it, don't crash, keep the build visible."""
    client = _FakeLibraryClient(
        payload_ids=[NEW_ID], known_ids=[], upstream_ids=[], names={}
    )

    class _EmptyResolver(CharacterMetadataResolver):
        async def resolve(self, char_id, language="en"):
            return None

        async def resolve_text(self, text_hash, language="en"):
            return None

    patch_enka(client, resolver=_EmptyResolver())

    showcase = await EnkaClient().fetch_showcase("901211014")

    assert len(showcase.characters) == 1
    character = showcase.characters[0]
    assert character.id == str(NEW_ID)
    assert character.name == placeholder_name(str(NEW_ID)), "the id stays visible"
    assert character.level == 90, "build data is shown even without a name"


async def test_unknown_id_is_logged(patch_enka, caplog):
    """A newly released character must be diagnosable from the logs."""
    client = _FakeLibraryClient(
        payload_ids=[NEW_ID], known_ids=[], upstream_ids=[], names={}
    )

    class _EmptyResolver(CharacterMetadataResolver):
        async def resolve(self, char_id, language="en"):
            return None

        async def resolve_text(self, text_hash, language="en"):
            return None

    patch_enka(client, resolver=_EmptyResolver())

    with caplog.at_level("INFO"):
        await EnkaClient().fetch_showcase("901211014")

    assert f"[ENKA] Unknown character ID: {NEW_ID}" in caplog.text


async def test_metadata_resolver_names_a_character_the_library_cannot(patch_enka):
    """When the library stays blind, the dynamic resolver supplies name/element/art."""
    client = _FakeLibraryClient(
        payload_ids=[NEW_ID], known_ids=[], upstream_ids=[], names={}
    )

    class _StubResolver(CharacterMetadataResolver):
        async def resolve(self, char_id, language="en"):
            return CharacterMeta(
                id=str(char_id), name=NEW_NAME, element="Ice", rarity=5,
                side_icon=f"UI_AvatarIcon_Side_{NEW_NAME}", source="test",
            )

        async def resolve_text(self, text_hash, language="en"):
            return None

    patch_enka(client, resolver=_StubResolver())

    character = (await EnkaClient().fetch_showcase("901211014")).characters[0]

    assert character.name == NEW_NAME
    assert character.element == "Ice"
    assert character.rarity == 5
    assert character.art == f"https://enka.network/ui/UI_Gacha_AvatarImg_{NEW_NAME}.png"


async def test_unresolved_character_never_yields_a_bogus_art_url(patch_enka):
    """An empty icon path must not become 'https://enka.network/ui/.png' (a certain 404)."""
    client = _FakeLibraryClient(
        payload_ids=[NEW_ID], known_ids=[], upstream_ids=[], names={}
    )

    class _EmptyResolver(CharacterMetadataResolver):
        async def resolve(self, char_id, language="en"):
            return None

        async def resolve_text(self, text_hash, language="en"):
            return None

    patch_enka(client, resolver=_EmptyResolver())

    character = (await EnkaClient().fetch_showcase("901211014")).characters[0]

    assert character.art is None
    assert character.icon is None


async def test_one_unparsable_character_does_not_discard_the_showcase(patch_enka):
    """A new artifact set / quality type breaking one character must not lose the others."""
    client = _FakeLibraryClient(
        payload_ids=[KNOWN_ID, NEW_ID],
        known_ids=[KNOWN_ID, NEW_ID],
        upstream_ids=[KNOWN_ID, NEW_ID],
        names={KNOWN_ID: KNOWN_NAME, NEW_ID: NEW_NAME},
    )
    real_parse = client.parse_showcase

    def exploding(payload):
        ids = [c["avatarId"] for c in payload.get("avatarInfoList", [])]
        if NEW_ID in ids:
            raise KeyError("QUALITY_ORANGE_SP_NEW")  # what enka.py raises for a new rarity
        return real_parse(payload)

    client.parse_showcase = exploding
    patch_enka(client)

    showcase = await EnkaClient().fetch_showcase("901211014")

    assert [c.name for c in showcase.characters] == [KNOWN_NAME]


async def test_totally_unparsable_payload_becomes_a_domain_error(patch_enka):
    """If nothing parses at all, surface a handled domain error rather than a raw crash."""
    client = _FakeLibraryClient(
        payload_ids=[KNOWN_ID], known_ids=[KNOWN_ID], upstream_ids=[KNOWN_ID],
        names={KNOWN_ID: KNOWN_NAME},
    )

    def always_explode(payload):
        raise ValueError("schema changed")

    client.parse_showcase = always_explode
    patch_enka(client)

    with pytest.raises(ApiUnavailable):
        await EnkaClient().fetch_showcase("901211014")


async def test_client_is_closed_even_on_failure(patch_enka):
    """The per-call library client must be released on every path."""
    client = _FakeLibraryClient(
        payload_ids=[KNOWN_ID], known_ids=[KNOWN_ID], upstream_ids=[KNOWN_ID],
        names={KNOWN_ID: KNOWN_NAME},
    )

    def always_explode(payload):
        raise ValueError("schema changed")

    client.parse_showcase = always_explode
    patch_enka(client)

    with pytest.raises(ApiUnavailable):
        await EnkaClient().fetch_showcase("901211014")
    assert client.closed


async def test_refresh_is_not_retried_within_the_cooldown(patch_enka):
    """A permanently unknown id must not download metadata on every single command."""
    client = _FakeLibraryClient(
        payload_ids=[NEW_ID], known_ids=[], upstream_ids=[], names={}
    )

    class _EmptyResolver(CharacterMetadataResolver):
        async def resolve(self, char_id, language="en"):
            return None

        async def resolve_text(self, text_hash, language="en"):
            return None

    # A shared refresher, as in production, with a real cooldown.
    refresher = EnkaAssetRefresher(ttl=10_000, force_cooldown=900)
    patch_enka(client, refresher=refresher, resolver=_EmptyResolver())

    enka_client = EnkaClient()
    for _ in range(3):
        await enka_client.fetch_showcase("901211014")

    assert client.update_calls == 1, "the cooldown must suppress the repeat refreshes"
