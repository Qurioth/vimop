import os
from datetime import datetime, timedelta, timezone

import discord
from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
RUN_EVERY_DAYS = int(os.getenv("RUN_EVERY_DAYS", "1"))
FORCE_RUN = os.getenv("FORCE_RUN", "false").lower() == "true"

# TARGET_CHANNEL_ID is retained for compatibility with the previous configuration.
raw_channel_ids = os.getenv("TARGET_CHANNEL_IDS") or os.getenv("TARGET_CHANNEL_ID", "")

try:
    TARGET_CHANNEL_IDS = tuple(
        int(channel_id.strip())
        for channel_id in raw_channel_ids.split(",")
        if channel_id.strip()
    )
except ValueError as error:
    raise RuntimeError(
        "TARGET_CHANNEL_IDS must contain comma-separated numeric channel IDs."
    ) from error

if not TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN is not configured.")
if not TARGET_CHANNEL_IDS:
    raise RuntimeError("TARGET_CHANNEL_IDS is not configured.")
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

        for channel_id in TARGET_CHANNEL_IDS:
            total_deleted += await self.cleanup_channel(channel_id, cutoff)

        print(f"Cleanup complete: {total_deleted} messages deleted in total.")

    async def cleanup_channel(self, channel_id: int, cutoff: datetime) -> int:
        channel = self.get_channel(channel_id)

        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden) as error:
                print(f"Channel {channel_id}: not found or not accessible: {error}")
                return 0

        if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
            print(f"Channel {channel_id}: unsupported channel type.")
            return 0

        deleted_count = 0
        checked_count = 0

        async for message in channel.history(limit=1000, before=cutoff):
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
