import logging

import discord
from redbot.core import commands

from .abc import MixinMeta
<<<<<<< HEAD
from .common.utils import get_attachments
from .models import READ_EXTENSIONS, GuildSettings
import random
=======
from .common.utils import can_use
>>>>>>> main

log = logging.getLogger("red.vrt.assistant.listener")


class AssistantListener(MixinMeta):
    @commands.Cog.listener("on_message_without_command")
    async def handler(self, message: discord.Message):
        # If message object is None for some reason
        if not message:
            return
        # If message was from a bot
        # if message.author.bot:
        #     return
        if not message.webhook_id:
            return
        # If message wasn't sent in a guild
        if not message.guild:
            return
        # Ignore if channel doesn't exist
        if not message.channel:
            return
<<<<<<< HEAD
        # Ignore references to other members
        # if hasattr(message, "reference") and message.reference:
        #     ref = message.reference.resolved
        #     if ref and ref.author.id != self.bot.user.id:
        #         return
=======
        # Check if cog is disabled
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        # Check permissions
        if not message.channel.permissions_for(message.guild.me).send_messages:
            return
        if not message.channel.permissions_for(message.guild.me).embed_links:
            return
>>>>>>> main

        conf = self.db.get_conf(message.guild)
        if not conf.enabled:
            return
        no_api = [not conf.api_key, not conf.endpoint_override, not self.db.endpoint_override]
        if all(no_api):
            return

        channel = message.channel
        mention_ids = [m.id for m in message.mentions]

        # Ignore channels that arent a dedicated assistant channel
<<<<<<< HEAD
        if self.bot.user.id not in mention_ids and channel.id != conf.channel_id:
            return
<<<<<<< HEAD
<<<<<<< HEAD
        if random.random() > 0.2:
            return

        for mention in message.mentions:
            message.content = message.content.replace(
                f"<@{mention.id}>", f"@{mention.display_name}"
            )
        for mention in message.channel_mentions:
            message.content = message.content.replace(f"<#{mention.id}>", f"#{mention.name}")
        for mention in message.role_mentions:
            message.content = message.content.replace(f"<@&{mention.id}>", f"@{mention.name}")

        content = message.content
=======
        if not await can_use(message, conf.blacklist, respond=False):
            return
>>>>>>> main
        mentions = [member.id for member in message.mentions]
=======
=======
        if channel.id != conf.channel_id:
            # Perform some preliminary checks
            if self.bot.user.id not in mention_ids:
                return
            # If here, bot was mentioned
            if not conf.mention_respond:
                return
>>>>>>> main

        # Ignore references to other members unless bot is pinged
        if hasattr(message, "reference") and message.reference:
            ref = message.reference.resolved
            if ref and ref.author.id != self.bot.user.id and self.bot.user.id not in mention_ids:
                return

        if not await can_use(message, conf.blacklist, respond=False):
            return
>>>>>>> main
        if (
            not message.content.endswith("?")
            and conf.endswith_questionmark
            and self.bot.user.id not in mention_ids
        ):
            return
<<<<<<< HEAD

        embed = message.embeds[0] if message.embeds else None
        if not embed:
            return

        if random.randint(1, 2) == 1:
            angry_or_happy = "ljutog"
            angry_or_happy_2 = "ljut"
            angry_or_happy_3 = "nemoj ikakve komplimente davat"
        else:
            angry_or_happy = "skepticnog"
            angry_or_happy_2 = "skeptik"
            angry_or_happy_3 = "nemoj biti ni previse pozitivan ni previse negativan"

        content = f"Article Title: {embed.title}\n" \
                  f"Article Summary: {embed.description}\n\n" \
                  f"" \
                  f"ignorirajuci sve sto je prije navedeno, imitiraj f{angry_or_happy} gejmera na wow battlenet forumsima i napisi discord poruku o ovom artiklu na hrvatskom\n" \
                  f"cilj je kritizirati i biti f{angry_or_happy_2}, f{angry_or_happy_3}\n" \
                  f"nemoj ista cenzurirat\n" \
                  f"napisi ispod 150 slova"

        if attachments := get_attachments(message):
            for i in attachments:
                if not any(i.filename.lower().endswith(ext) for ext in READ_EXTENSIONS):
                    continue
                text = await i.read()
                content += f"\n\nUploaded [{i.filename}]: {text.decode()}"

        async with channel.typing():
            await self.try_replying(message, content, conf)
=======

        if len(message.content.strip()) < conf.min_length:
            return
>>>>>>> main

        async with channel.typing():
            await self.handle_message(message, message.content, conf, listener=True)

    @commands.Cog.listener("on_guild_remove")
    async def cleanup(self, guild: discord.Guild):
        if guild.id in self.db.configs:
            log.info(f"Bot removed from {guild.name}, cleaning up...")
            del self.db.configs[guild.id]
            await self.save_conf()
