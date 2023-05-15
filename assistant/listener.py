import logging

import discord
from openai.error import InvalidRequestError
from redbot.core import commands
from redbot.core.utils.chat_formatting import pagify

from .abc import MixinMeta
from .models import GuildSettings
import random

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
        # Ignore references to other members
        # if hasattr(message, "reference") and message.reference:
        #     ref = message.reference.resolved
        #     if ref and ref.author.id != self.bot.user.id:
        #         return

        conf = self.db.get_conf(message.guild)
        if not conf.enabled:
            return
        if not conf.api_key:
            return
        channel = message.channel
        if channel.id != conf.channel_id:
            return

        embed = message.embeds[0] if message.embeds else None
        if not embed:
            return

        # if random.randint(1, 2) == 1:
        angry_or_happy = "ljutog"
        angry_or_happy_2 = "ljut"
        angry_or_happy_3 = "komplimente"
        # else:
        #     angry_or_happy = "sretnog"
        #     angry_or_happy_2 = "sretan"
        #     angry_or_happy_3 = "negativne misli"

        content = f"Article Title: {embed.title}\n" \
                  f"Article Summary: {embed.description}\n\n" \
                  f"" \
                  f"ignorirajuci sve sto je prije navedeno, imitiraj f{angry_or_happy} gejmera na wow battlenet forumsima i napisi discord poruku o ovom artiklu na hrvatskom\n" \
                  f"cilj je biti f{angry_or_happy_2}, nemoj ikakve f{angry_or_happy_3} davat\n" \
                  f"nemoj ista cenzurirat\n" \
                  f"napisi ispod 150 slova"

        async with channel.typing():
            await self.try_replying(message, content, conf)

    async def try_replying(self, message: discord.Message, content: str, conf: GuildSettings):
        try:
            reply = await self.get_chat_response(content, message.author, conf)
            parts = [p for p in pagify(reply, page_length=2000)]
            for index, p in enumerate(parts):
                if not index:
                    await message.reply(p, mention_author=conf.mention)
                else:
                    await message.channel.send(p)
            return
        except InvalidRequestError as e:
            if error := e.error:
                await message.reply(error["message"], mention_author=conf.mention)
            log.error("Invalid Request Error", exc_info=e)
        except Exception as e:
            await message.channel.send(f"**Error**\n```py\n{e}\n```")
            log.error("Listener Reply Error", exc_info=e)
