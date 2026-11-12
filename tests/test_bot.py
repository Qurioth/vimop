import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import bot
from conftest import (
    make_category,
    make_channel,
    make_guild,
    make_http_error,
    make_message,
    make_role,
)


def freeze_now(monkeypatch, now):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(bot, "datetime", FixedDatetime)


# toordinal() が偶数／奇数になる日付（RUN_EVERY_DAYS=2 の判定用）
EVEN_DAY = datetime(2026, 11, 12, 19, 0, tzinfo=timezone.utc)
ODD_DAY = EVEN_DAY + timedelta(days=1)
assert EVEN_DAY.toordinal() % 2 == 0
assert ODD_DAY.toordinal() % 2 == 1


# --- validate_config -------------------------------------------------------


def test_validate_config_accepts_valid_settings():
    bot.validate_config()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("TOKEN", None, "DISCORD_BOT_TOKEN"),
        ("TOKEN", "", "DISCORD_BOT_TOKEN"),
        ("TARGET_ROLE_NAME", "", "TARGET_ROLE_NAME"),
        ("RETENTION_HOURS", 0, "RETENTION_HOURS"),
        ("RETENTION_HOURS", -1, "RETENTION_HOURS"),
        ("RUN_EVERY_DAYS", 0, "RUN_EVERY_DAYS"),
    ],
)
def test_validate_config_rejects_invalid_settings(monkeypatch, name, value, message):
    monkeypatch.setattr(bot, name, value)

    with pytest.raises(RuntimeError, match=message):
        bot.validate_config()


# --- get_target_role -------------------------------------------------------


def test_get_target_role_returns_matching_role():
    role = make_role("Vimop")
    guild = make_guild(roles=[make_role("@everyone"), role, make_role("Other")])

    assert bot.CleanerClient.get_target_role(guild) is role


def test_get_target_role_requires_exact_name_match():
    guild = make_guild(roles=[make_role("vimop"), make_role("Vimop ")])

    with pytest.raises(RuntimeError, match="found 0"):
        bot.CleanerClient.get_target_role(guild)


def test_get_target_role_rejects_duplicate_roles():
    guild = make_guild(roles=[make_role("Vimop"), make_role("Vimop")])

    with pytest.raises(RuntimeError, match="found 2"):
        bot.CleanerClient.get_target_role(guild)


def test_get_target_role_reports_missing_permissions():
    role = make_role("Vimop", manage_messages=False, read_message_history=False)
    guild = make_guild(roles=[role])

    with pytest.raises(RuntimeError) as excinfo:
        bot.CleanerClient.get_target_role(guild)

    message = str(excinfo.value)
    assert "manage_messages" in message
    assert "read_message_history" in message
    assert "view_channel" not in message


# --- is_cleanup_target -----------------------------------------------------


def test_channel_with_role_overwrite_is_target():
    role = make_role()
    channel = make_channel(overwrites={role: object()})

    assert bot.CleanerClient.is_cleanup_target(channel, role) is True
    channel.permissions_for.assert_called_once_with(role)


def test_channel_without_role_is_not_target():
    role = make_role()
    everyone = make_role("@everyone")
    channel = make_channel(overwrites={everyone: object()})

    assert bot.CleanerClient.is_cleanup_target(channel, role) is False


def test_channel_synced_with_category_containing_role_is_target():
    role = make_role()
    category = make_category(overwrites={role: object()})
    channel = make_channel(category=category, permissions_synced=True)

    assert bot.CleanerClient.is_cleanup_target(channel, role) is True


def test_channel_not_synced_with_category_is_not_target():
    role = make_role()
    category = make_category(overwrites={role: object()})
    channel = make_channel(category=category, permissions_synced=False)

    assert bot.CleanerClient.is_cleanup_target(channel, role) is False


def test_synced_channel_in_category_without_role_is_not_target():
    role = make_role()
    channel = make_channel(category=make_category(), permissions_synced=True)

    assert bot.CleanerClient.is_cleanup_target(channel, role) is False


@pytest.mark.parametrize(
    "missing",
    ["view_channel", "read_message_history", "manage_messages"],
)
def test_channel_without_effective_permission_is_not_target(missing):
    role = make_role()
    permissions = {
        "view_channel": True,
        "read_message_history": True,
        "manage_messages": True,
        missing: False,
    }
    channel = make_channel(
        overwrites={role: object()},
        effective_permissions=permissions,
    )

    assert not bot.CleanerClient.is_cleanup_target(channel, role)


# --- cleanup_channel -------------------------------------------------------


def test_cleanup_channel_deletes_unpinned_messages(client):
    cutoff = EVEN_DAY
    messages = [make_message(), make_message(pinned=True), make_message()]
    channel = make_channel(messages=messages)

    deleted = asyncio.run(client.cleanup_channel(channel, cutoff))

    assert deleted == 2
    channel.history.assert_called_once_with(limit=None, before=cutoff)
    messages[0].delete.assert_awaited_once()
    messages[1].delete.assert_not_awaited()
    messages[2].delete.assert_awaited_once()


def test_cleanup_channel_stops_on_forbidden(client, capsys):
    forbidden = make_http_error(discord.Forbidden, status=403, reason="Forbidden")
    messages = [make_message(), make_message(delete_error=forbidden), make_message()]
    channel = make_channel(messages=messages)

    deleted = asyncio.run(client.cleanup_channel(channel, EVEN_DAY))

    assert deleted == 1
    messages[2].delete.assert_not_awaited()
    assert "missing permission" in capsys.readouterr().out


def test_cleanup_channel_continues_after_http_error(client, capsys):
    messages = [make_message(delete_error=make_http_error()), make_message()]
    channel = make_channel(messages=messages)

    deleted = asyncio.run(client.cleanup_channel(channel, EVEN_DAY))

    assert deleted == 1
    messages[1].delete.assert_awaited_once()
    output = capsys.readouterr().out
    assert "failed to delete a message" in output
    assert "checked 2, deleted 1." in output


# --- cleanup_guild ---------------------------------------------------------


def test_cleanup_guild_only_processes_text_and_voice_targets(client):
    role = make_role()
    text = make_channel(1, overwrites={role: object()})
    voice = make_channel(2, channel_type=discord.VoiceChannel, overwrites={role: object()})
    unrelated = make_channel(3)
    forum = make_channel(4, channel_type=discord.ForumChannel, overwrites={role: object()})
    guild = make_guild(roles=[role], channels=[text, voice, unrelated, forum])
    client.cleanup_channel = AsyncMock(side_effect=[3, 4])

    deleted = asyncio.run(client.cleanup_guild(guild, role, EVEN_DAY))

    assert deleted == 7
    processed = [call.args[0] for call in client.cleanup_channel.await_args_list]
    assert processed == [text, voice]


# --- cleanup ---------------------------------------------------------------


def test_cleanup_skips_when_not_scheduled_day(client, monkeypatch, capsys):
    monkeypatch.setattr(bot, "RUN_EVERY_DAYS", 2)
    freeze_now(monkeypatch, ODD_DAY)
    client.test_guilds = [make_guild(roles=[make_role()])]
    client.cleanup_guild = AsyncMock(return_value=0)

    asyncio.run(client.cleanup())

    client.cleanup_guild.assert_not_awaited()
    assert "Skip: not a scheduled cleanup day." in capsys.readouterr().out


def test_cleanup_runs_on_scheduled_day(client, monkeypatch):
    monkeypatch.setattr(bot, "RUN_EVERY_DAYS", 2)
    freeze_now(monkeypatch, EVEN_DAY)
    client.test_guilds = [make_guild(roles=[make_role()])]
    client.cleanup_guild = AsyncMock(return_value=0)

    asyncio.run(client.cleanup())

    client.cleanup_guild.assert_awaited_once()


def test_cleanup_force_run_ignores_schedule(client, monkeypatch):
    monkeypatch.setattr(bot, "RUN_EVERY_DAYS", 2)
    monkeypatch.setattr(bot, "FORCE_RUN", True)
    freeze_now(monkeypatch, ODD_DAY)
    client.test_guilds = [make_guild(roles=[make_role()])]
    client.cleanup_guild = AsyncMock(return_value=0)

    asyncio.run(client.cleanup())

    client.cleanup_guild.assert_awaited_once()


def test_cleanup_uses_retention_hours_for_cutoff(client, monkeypatch):
    monkeypatch.setattr(bot, "RETENTION_HOURS", 168)
    freeze_now(monkeypatch, EVEN_DAY)
    role = make_role()
    guild = make_guild(roles=[role])
    client.test_guilds = [guild]
    client.cleanup_guild = AsyncMock(return_value=0)

    asyncio.run(client.cleanup())

    client.cleanup_guild.assert_awaited_once_with(
        guild,
        role,
        EVEN_DAY - timedelta(days=7),
    )


def test_cleanup_skips_failing_guilds_and_totals_the_rest(client, monkeypatch, capsys):
    freeze_now(monkeypatch, EVEN_DAY)
    no_role = make_guild(1, "No Role")
    forbidden = make_guild(2, "Forbidden", roles=[make_role()])
    ok = make_guild(3, "OK", roles=[make_role()])
    client.test_guilds = [no_role, forbidden, ok]
    client.cleanup_guild = AsyncMock(
        side_effect=[make_http_error(discord.Forbidden, status=403), 5],
    )

    asyncio.run(client.cleanup())

    output = capsys.readouterr().out
    assert "WARNING: skipping server No Role (1)" in output
    assert "WARNING: skipping server Forbidden (2)" in output
    assert "Cleanup complete: 5 messages deleted in total." in output


# --- on_ready --------------------------------------------------------------


def test_on_ready_runs_cleanup_once_and_closes(client):
    client.cleanup = AsyncMock()

    asyncio.run(client.on_ready())
    asyncio.run(client.on_ready())

    client.cleanup.assert_awaited_once()
    client.close.assert_awaited_once()
    assert client.cleanup_error is None


def test_on_ready_records_error_and_still_closes(client):
    error = ValueError("boom")
    client.cleanup = AsyncMock(side_effect=error)

    asyncio.run(client.on_ready())

    assert client.cleanup_error is error
    client.close.assert_awaited_once()


# --- main ------------------------------------------------------------------


def test_main_runs_client_with_token(monkeypatch):
    run = MagicMock()
    monkeypatch.setattr(bot.CleanerClient, "run", run)

    bot.main()

    run.assert_called_once_with("test-token")


def test_main_raises_cleanup_error(monkeypatch):
    error = ValueError("cleanup failed")

    def fake_run(self, token):
        self.cleanup_error = error

    monkeypatch.setattr(bot.CleanerClient, "run", fake_run)

    with pytest.raises(ValueError, match="cleanup failed"):
        bot.main()


def test_main_does_not_connect_with_invalid_config(monkeypatch):
    monkeypatch.setattr(bot, "TOKEN", None)
    run = MagicMock()
    monkeypatch.setattr(bot.CleanerClient, "run", run)

    with pytest.raises(RuntimeError, match="DISCORD_BOT_TOKEN"):
        bot.main()

    run.assert_not_called()
