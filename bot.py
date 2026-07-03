import os
from datetime import datetime, timedelta, timezone

import discord
from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
RUN_EVERY_DAYS = int(os.getenv("RUN_EVERY_DAYS", "1"))
FORCE_RUN = os.getenv("FORCE_RUN", "false").lower() == "true"
TARGET_ROLE_NAME = os.getenv("TARGET_ROLE_NAME", "Vimop")

if not TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN is not configured.")
if not TARGET_ROLE_NAME:
    raise RuntimeError("TARGET_ROLE_NAME is not configured.")
if RETENTION_HOURS <= 0:
    raise RuntimeError("RETENTION_HOURS must be at least 1.")
if RUN_EVERY_DAYS <= 0:
    raise RuntimeError("RUN_EVERY_DAYS must be at least 1.")


class CleanerClient(discord.Client):
    def __init__(self, **options):
        super().__init__(**options)
        self.cleanup_started = False
        self.cleanup_error: Exception | None = None

    async def on_ready(self):
        if self.cleanup_started:
            return
        self.cleanup_started = True

        print(f"Logged in as {self.user}")
        print(f"Connected servers: {len(self.guilds)}")
        for guild in self.guilds:
            print(f"- {guild.name} ({guild.id})")

        try:
            await self.cleanup()
        except Exception as error:
            self.cleanup_error = error
        finally:
            await self.close()

    async def cleanup(self):
        now = datetime.now(timezone.utc)

        # The workflow runs daily; this guard makes scheduled runs occur every N days.
        if not FORCE_RUN and now.toordinal() % RUN_EVERY_DAYS != 0:
            print("Skip: not a scheduled cleanup day.")
            return

        cutoff = now - timedelta(hours=RETENTION_HOURS)
        total_deleted = 0

        for guild in self.guilds:
            try:
                target_role = self.get_target_role(guild)
                total_deleted += await self.cleanup_guild(
                    guild,
                    target_role,
                    cutoff,
                )
            except (RuntimeError, discord.Forbidden) as error:
                print(
                    f"WARNING: skipping server {guild.name} ({guild.id}): {error}"
                )

        print(f"Cleanup complete: {total_deleted} messages deleted in total.")

    @staticmethod
    def get_target_role(guild: discord.Guild) -> discord.Role:
        matching_roles = [role for role in guild.roles if role.name == TARGET_ROLE_NAME]
        if len(matching_roles) != 1:
            raise RuntimeError(
                f'Server {guild.id} must have exactly one role named '
                f'"{TARGET_ROLE_NAME}"; found {len(matching_roles)}.'
            )

        target_role = matching_roles[0]
        required_permissions = (
            "view_channel",
            "manage_messages",
            "read_message_history",
        )
        missing_permissions = [
            name
            for name in required_permissions
            if not getattr(target_role.permissions, name)
        ]
        if missing_permissions:
            raise RuntimeError(
                f'Role "{TARGET_ROLE_NAME}" in server {guild.id} is missing '
                f'required permissions: {", ".join(missing_permissions)}.'
            )

        return target_role

    async def cleanup_guild(
        self,
        guild: discord.Guild,
        target_role: discord.Role,
        cutoff: datetime,
    ) -> int:

        target_channels = []
        for channel in guild.channels:
            if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                continue

            if self.is_cleanup_target(channel, target_role):
                target_channels.append(channel)

        print(
            f'Server {guild.id}: found {len(target_channels)} channels with an '
            f'explicit permission entry for role "{TARGET_ROLE_NAME}".'
        )
        for channel in target_channels:
            print(f"Server {guild.id}: cleanup target #{channel.name} ({channel.id})")

        deleted_count = 0
        for channel in target_channels:
            deleted_count += await self.cleanup_channel(channel, cutoff)

        return deleted_count

    @staticmethod
    def is_cleanup_target(
        channel: discord.TextChannel | discord.VoiceChannel,
        role: discord.Role,
    ) -> bool:
        # The role must be explicitly selected on the channel or its synchronized
        # category. @everyone and unrelated roles cannot select a cleanup target.
        category = channel.category
        role_is_selected = role in channel.overwrites or (
            category is not None
            and channel.permissions_synced
            and role in category.overwrites
        )
        if not role_is_selected:
            return False

        effective = channel.permissions_for(role)
        return (
            effective.view_channel
            and effective.read_message_history
            and effective.manage_messages
        )

    async def cleanup_channel(
        self,
        channel: discord.TextChannel | discord.VoiceChannel,
        cutoff: datetime,
    ) -> int:
        channel_id = channel.id

        deleted_count = 0
        checked_count = 0

        async for message in channel.history(limit=None, before=cutoff):
            checked_count += 1
            if message.pinned:
                continue

            try:
                await message.delete()
                deleted_count += 1
            except discord.Forbidden:
                print(
                    f"Channel {channel_id}: missing permission. "
                    "Check View Channel, Read Message History, and Manage Messages."
                )
                break
            except discord.HTTPException as error:
                print(f"Channel {channel_id}: failed to delete a message: {error}")

        print(
            f"Channel {channel_id}: checked {checked_count}, "
            f"deleted {deleted_count}."
        )
        return deleted_count


intents = discord.Intents.default()
client = CleanerClient(intents=intents)
client.run(TOKEN)

if client.cleanup_error is not None:
    raise client.cleanup_error
