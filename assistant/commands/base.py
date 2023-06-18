import logging

import discord
from redbot.core import commands

from ..abc import MixinMeta
from ..common.utils import can_use

log = logging.getLogger("red.vrt.assistant.base")


class Base(MixinMeta):
    @commands.command(name="chat", aliases=["ask"])
    @commands.guild_only()
    @commands.cooldown(1, 6, commands.BucketType.user)
    async def ask_question(self, ctx: commands.Context, *, question: str):
        """
        Chat with [botname]!

        Conversations are *Per* user *Per* channel, meaning a conversation you have in one channel will be kept in memory separately from another conversation in a separate channel

        **Optional Arguments**
        `--outputfile <filename>` - uploads a file with the reply instead (no spaces)
        `--extract` - extracts code blocks from the reply

        **Example**
        `[p]chat write a python script that prints "Hello World!"`
        - Including `--outputfile hello.py` will output a file containing the whole response.
        - Including `--outputfile hello.py --extract` will output a file containing just the code blocks and send the rest as text.
        - Including `--extract` will send the code separately from the reply
        """
        conf = self.db.get_conf(ctx.guild)
        if not conf.api_key:
            return await ctx.send("This command requires an API key from OpenAI to be configured!")
        if not await can_use(ctx.message, conf.blacklist):
            return
        # embed_links perm handled in following functions
        async with ctx.typing():
            await self.handle_message(ctx.message, question, conf)

    @commands.command(name="convostats")
    @commands.guild_only()
    async def token_count(self, ctx: commands.Context, *, user: discord.Member = None):
        """
        Check the token and message count of yourself or another user's conversation for this channel

        Conversations are *Per* user *Per* channel, meaning a conversation you have in one channel will be kept in memory separately from another conversation in a separate channel

        Conversations are only stored in memory until the bot restarts or the cog reloads
        """
        if not user:
            user = ctx.author
        conf = self.db.get_conf(ctx.guild)
<<<<<<< HEAD
<<<<<<< HEAD
        conversation = self.chats.get_conversation(user)
=======
        conversation = self.chats.get_conversation(user.id, ctx.channel.id, ctx.guild.id)
>>>>>>> main
=======
        conversation = self.db.get_conversation(user.id, ctx.channel.id, ctx.guild.id)
>>>>>>> main
        messages = len(conversation.messages)
        embed = discord.Embed(
            description=(
                f"**Conversation stats for {user.mention} in {ctx.channel.mention}**\n"
                f"`Messages: `{messages}\n"
                f"`Tokens:   `{conversation.user_token_count()}\n"
                f"`Expired:  `{conversation.is_expired(conf)}"
            ),
            color=user.color,
        )
        await ctx.send(embed=embed)

    @commands.command(name="clearconvo")
    @commands.guild_only()
    async def clear_convo(self, ctx: commands.Context):
        """
        Reset your conversation

        This will clear all message history between you and the bot for this channel
        """
<<<<<<< HEAD
<<<<<<< HEAD
        conversation = self.chats.get_conversation(ctx.author)
=======
        conversation = self.chats.get_conversation(ctx.author.id, ctx.channel.id, ctx.guild.id)
>>>>>>> main
=======
        conversation = self.db.get_conversation(ctx.author.id, ctx.channel.id, ctx.guild.id)
>>>>>>> main
        conversation.reset()
        await ctx.send("Your conversation in this channel has been reset!")
