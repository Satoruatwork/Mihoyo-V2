"""Tests for the broadcast service, store enumeration, and target-flag parsing."""

from __future__ import annotations

import pytest

from bot.commands.broadcast import _parse_target
from bot.services.broadcast_service import (
    BroadcastService,
    BroadcastTarget,
    SendOutcome,
)

# --- store enumeration + pruning --------------------------------------------


async def test_all_users_and_groups(store):
    await store.link_uid(1, "601111111")
    await store.link_uid(2, "702222222")
    await store.register_group(-100123)
    assert set(await store.all_users()) == {1, 2}
    assert set(await store.all_groups()) == {-100123}


async def test_discard_users_and_groups(store):
    await store.link_uid(1, "601111111")
    await store.register_group(-100123)
    await store.discard_users([1])
    await store.discard_groups([-100123])
    assert await store.all_users() == []
    assert await store.all_groups() == []


# --- recipient resolution ----------------------------------------------------


@pytest.mark.parametrize(
    "target, expected",
    [
        (BroadcastTarget.USERS, {1, 2}),
        (BroadcastTarget.GROUPS, {-100123}),
        (BroadcastTarget.ALL, {1, 2, -100123}),
    ],
)
async def test_recipients_by_target(store, target, expected):
    await store.link_uid(1, "601111111")
    await store.link_uid(2, "702222222")
    await store.register_group(-100123)
    svc = BroadcastService(store)
    assert set(await svc.recipients(target)) == expected


# --- broadcast fan-out -------------------------------------------------------


async def test_broadcast_tallies_outcomes_and_collects_blocked(store):
    svc = BroadcastService(store)
    chat_ids = [1, 2, 3, -100]  # user 2 blocked, group -100 transient failure

    async def send_fn(chat_id: int) -> SendOutcome:
        if chat_id == 2:
            return SendOutcome.BLOCKED
        if chat_id == -100:
            return SendOutcome.FAILED
        return SendOutcome.SENT

    result = await svc.broadcast(chat_ids, send_fn, per_second=10_000)
    assert result.total == 4
    assert result.sent == 2
    assert result.blocked == 1
    assert result.failed == 1
    assert result.blocked_ids == [2]


async def test_broadcast_contains_send_fn_exceptions(store):
    svc = BroadcastService(store)

    async def boom(chat_id: int) -> SendOutcome:
        raise RuntimeError("network blip")

    result = await svc.broadcast([1, 2], boom, per_second=10_000)
    assert result.failed == 2 and result.sent == 0


async def test_broadcast_invokes_progress_callback(store):
    svc = BroadcastService(store)
    seen: list[int] = []

    async def send_fn(chat_id: int) -> SendOutcome:
        return SendOutcome.SENT

    async def progress(done: int, result) -> None:
        seen.append(done)

    await svc.broadcast(list(range(1, 6)), send_fn, per_second=10_000, progress=progress, progress_every=2)
    assert seen == [2, 4]  # fired every 2 deliveries


# --- target-flag parsing -----------------------------------------------------


def test_parse_target_defaults_to_users():
    target, rest = _parse_target(["hello", "world"])
    assert target is BroadcastTarget.USERS
    assert rest == ["hello", "world"]


@pytest.mark.parametrize(
    "flag, target",
    [("--users", BroadcastTarget.USERS), ("--groups", BroadcastTarget.GROUPS), ("--all", BroadcastTarget.ALL)],
)
def test_parse_target_reads_leading_flag(flag, target):
    parsed, rest = _parse_target([flag, "the", "message"])
    assert parsed is target
    assert rest == ["the", "message"]


def test_parse_target_ignores_flag_not_leading():
    # A '--all' that isn't the first token stays part of the message.
    target, rest = _parse_target(["hey", "--all"])
    assert target is BroadcastTarget.USERS
    assert rest == ["hey", "--all"]
