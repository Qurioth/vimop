from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import bot


REQUIRED_PERMISSIONS = {
    "view_channel": True,
    "read_message_history": True,
    "manage_messages": True,
}


@pytest.fixture(autouse=True)
def config(monkeypatch):
    """ローカルの .env に左右されないよう、設定値をテスト用に固定する。"""
    monkeypatch.setattr(bot, "TOKEN", "test-token")
    monkeypatch.setattr(bot, "TARGET_ROLE_NAME", "Vimop")
    monkeypatch.setattr(bot, "RETENTION_HOURS", 168)
    monkeypatch.setattr(bot, "RUN_EVERY_DAYS", 1)
    monkeypatch.setattr(bot, "FORCE_RUN", False)


@pytest.fixture
def client(monkeypatch):
    """Discordに接続しない CleanerClient。guilds と close を差し替える。"""
    monkeypatch.setattr(
        bot.CleanerClient,
        "guilds",
        property(lambda self: self.test_guilds),
    )
    instance = bot.CleanerClient(intents=discord.Intents.default())
    instance.test_guilds = []
    instance.close = AsyncMock()
    return instance


def make_role(name="Vimop", **permissions):
    perms = {**REQUIRED_PERMISSIONS, **permissions}
    role = MagicMock(name=f"Role({name})")
    role.name = name
    role.permissions = discord.Permissions(**perms)
    return role


def make_guild(guild_id=1, name="Test Server", roles=(), channels=()):
    return SimpleNamespace(
        id=guild_id,
        name=name,
        roles=list(roles),
        channels=list(channels),
    )


def make_channel(
    channel_id=100,
    name="general",
    channel_type=discord.TextChannel,
    overwrites=None,
    category=None,
    permissions_synced=False,
    effective_permissions=None,
    messages=(),
):
    channel = MagicMock(spec=channel_type)
    channel.id = channel_id
    channel.name = name
    channel.overwrites = overwrites or {}
    channel.category = category
    channel.permissions_synced = permissions_synced
    channel.permissions_for.return_value = discord.Permissions(
        **(REQUIRED_PERMISSIONS if effective_permissions is None else effective_permissions)
    )

    async def history(**kwargs):
        for message in messages:
            yield message

    channel.history = MagicMock(side_effect=history)
    return channel


def make_category(overwrites=None):
    return SimpleNamespace(overwrites=overwrites or {})


def make_message(pinned=False, delete_error=None):
    message = MagicMock()
    message.pinned = pinned
    message.delete = AsyncMock(side_effect=delete_error)
    return message


def make_http_error(error_class=discord.HTTPException, status=500, reason="Error"):
    response = SimpleNamespace(status=status, reason=reason)
    return error_class(response, "test error")
