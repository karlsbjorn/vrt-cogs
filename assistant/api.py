import asyncio
import logging
import sys
from datetime import datetime
from typing import Union

import discord
import pytz
from aiocache import cached
from redbot.core import version_info
from redbot.core.utils.chat_formatting import humanize_list

from .abc import MixinMeta
from .common.utils import get_chat, get_embedding, num_tokens_from_string
from .models import Conversation, GuildSettings

log = logging.getLogger("red.vrt.assistant.api")


class API(MixinMeta):
    @cached(ttl=30)
    async def get_chat_response(
        self,
        message: str,
        author: discord.Member,
        channel: Union[discord.TextChannel, discord.Thread, discord.ForumChannel],
        conf: GuildSettings,
    ) -> str:
        conversation = self.chats.get_conversation(author, channel)
        try:
            reply = await asyncio.to_thread(
                self.prepare_call, message, author, channel, conf, conversation
            )
        finally:
            conversation.cleanup(conf)
        return reply

    def prepare_call(
        self,
        message: str,
        author: discord.Member,
        channel: Union[discord.TextChannel, discord.Thread, discord.ForumChannel],
        conf: GuildSettings,
        conversation: Conversation,
    ) -> str:
        timestamp = f"<t:{round(datetime.now().timestamp())}:F>"
        try:
            created = f"<t:{round(author.guild.created_at.timestamp())}:F>"
        except AttributeError:
            created = "Unknown"
        day = datetime.now().astimezone().strftime("%A")
        date = datetime.now().astimezone().strftime("%B %d, %Y")
        time = datetime.now().astimezone().strftime("%I:%M %p %Z")
        try:
            roles = [role.name for role in author.roles]
        except AttributeError:
            roles = ["Wowhead"]
        try:
            params = {
                "botname": self.bot.user.name,
                "timestamp": timestamp,
                "day": day,
                "date": date,
                "time": time,
                "members": author.guild.member_count,
                "user": author.display_name,
                "datetime": str(datetime.now()),
                "roles": humanize_list(roles),
                "avatar": author.avatar.url if author.avatar else "",
                "owner": author.guild.owner,
                "servercreated": created,
                "server": author.guild.name,
                "messages": len(conversation.messages),
                "retention": conf.max_retention,
                "retentiontime": conf.max_retention_time,
            }
        except AttributeError:
            params = {
                "botname": self.bot.user.name,
                "timestamp": timestamp,
                "day": day,
                "date": date,
                "time": time,
                "members": 200,
                "user": author.display_name,
                "datetime": str(datetime.now()),
                "roles": humanize_list(roles),
                "avatar": author.avatar.url if author.avatar else "",
                "owner": "Frane",
                "servercreated": created,
                "server": "Jahaci Rumene Kadulje",
                "messages": len(conversation.messages),
                "retention": conf.max_retention,
                "retentiontime": conf.max_retention_time,
            }

        query_embedding = get_embedding(text=message, api_key=conf.api_key)
        if not query_embedding:
            log.info(f"Could not get embedding for message: {message}")
        system_prompt = conf.system_prompt.format(**params)
        initial_prompt = conf.prompt.format(**params)

        # Dynamically clean up the conversation to prevent going over token limit
        max_usage = round(conf.max_tokens * 0.9)
        prompt_tokens = num_tokens_from_string(system_prompt + initial_prompt)
        while (conversation.token_count() + prompt_tokens) > max_usage:
            conversation.messages.pop(0)

        total_tokens = conversation.token_count() + prompt_tokens + num_tokens_from_string(message)

        embedding_context = ""
        has_context = False
        for i in conf.get_related_embeddings(query_embedding):
            if num_tokens_from_string(f"\nContext:\n{i[1]}\n\n") + total_tokens < max_usage:
                embedding_context += f"{i[1]}\n\n"
                has_context = True

        if has_context and conf.dynamic_embedding:
            initial_prompt += f"\nContext:\n{embedding_context}"
        elif has_context and not conf.dynamic_embedding:
            message = f"Context:\n{embedding_context}\n\n{author.display_name}: {message}"

        conversation.update_messages(message, "user")
        messages = conversation.prepare_chat(system_prompt, initial_prompt)
        reply = get_chat(model=conf.model, messages=messages, temperature=0, api_key=conf.api_key)
        conversation.update_messages(reply, "assistant")
        return reply
