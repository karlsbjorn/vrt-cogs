import asyncio
import functools
import json
import logging
import multiprocessing as mp
import re
import traceback
from datetime import datetime
from inspect import iscoroutinefunction
from io import BytesIO
from typing import Callable, Dict, List, Optional, Union

import discord
import pytz
from openai.error import (
    APIConnectionError,
    AuthenticationError,
    InvalidRequestError,
    RateLimitError,
)
from redbot.core import bank
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import box, humanize_number, pagify

from ..abc import MixinMeta
from .constants import READ_EXTENSIONS, SUPPORTS_FUNCTIONS
from .models import Conversation, GuildSettings
from .utils import (
    extract_code_blocks,
    extract_code_blocks_with_lang,
    get_attachments,
    get_params,
    process_username,
    remove_code_blocks,
)

log = logging.getLogger("red.vrt.assistant.chathandler")
_ = Translator("Assistant", __file__)


@cog_i18n(_)
class ChatHandler(MixinMeta):
    async def handle_message(
        self, message: discord.Message, question: str, conf: GuildSettings, listener: bool = False
    ) -> str:
        outputfile_pattern = r"--outputfile\s+([^\s]+)"
        extract_pattern = r"--extract"
        get_last_message_pattern = r"--last"

        # Extract the optional arguments and their values
        outputfile_match = re.search(outputfile_pattern, question)
        extract_match = re.search(extract_pattern, question)
        get_last_message_match = re.search(get_last_message_pattern, question)

        # Remove the optional arguments from the input string to obtain the question variable
        question = re.sub(outputfile_pattern, "", question)
        question = re.sub(extract_pattern, "", question)
        question = re.sub(get_last_message_pattern, "", question)

        # Check if the optional arguments were present and set the corresponding variables
        outputfile = outputfile_match.group(1) if outputfile_match else None
        extract = bool(extract_match)
        get_last_message = bool(get_last_message_match)

        question = question.replace(self.bot.user.mention, self.bot.user.display_name)

        for mention in message.mentions:
            question = question.replace(
                f"<@{mention.id}>",
                f"[Username: {mention.name} | Displayname: {mention.display_name} | Mention: {mention.mention}]",
            )
        for mention in message.channel_mentions:
            question = question.replace(
                f"<#{mention.id}>",
                f"[Channel: {mention.name} | Mention: {mention.mention}]",
            )
        for mention in message.role_mentions:
            mention.__dict__
            question = question.replace(
                f"<@&{mention.id}>",
                f"[Role: {mention.name} | Mention: {mention.mention}]",
            )
        for i in get_attachments(message):
            has_extension = i.filename.count(".") > 0
            if not any(i.filename.lower().endswith(ext) for ext in READ_EXTENSIONS) and has_extension:
                continue

            text = await i.read()

            if isinstance(text, bytes):
                try:
                    text = text.decode()
                except UnicodeDecodeError:
                    pass
                except Exception as e:
                    log.info(f"Failed to decode content of {i.filename}", exc_info=e)

            if i.filename == "message.txt":
                question += f"\n\n### Uploaded File:\n{text}\n"
            else:
                question += f"\n\n### Uploaded File ({i.filename}):\n{text}\n"

        # If referencing a message that isnt part of the user's conversation, include the context
        if hasattr(message, "reference") and message.reference:
            ref = message.reference.resolved
            if ref and ref.author.id != message.author.id:
                # If we're referencing the bot, make sure the bot's message isnt referencing the convo
                include = True
                if hasattr(ref, "reference") and ref.reference:
                    subref = ref.reference.resolved
                    # Make sure the message being referenced isnt just the bot replying
                    if subref and subref.author.id != message.author.id:
                        include = False

                if include:
                    question = (
                        f"{ref.author.name} said: {ref.content}\n\n"
                        f"{message.author.name} replying to {ref.author.name}: {question}"
                    )

        if get_last_message:
            conversation = self.db.get_conversation(message.author.id, message.channel.id, message.guild.id)
            reply = conversation.messages[-1]["content"] if conversation.messages else _("No message history!")
        else:
            try:
                reply = await self.get_chat_response(
                    question,
                    message.author,
                    message.guild,
                    message.channel,
                    conf,
                    message_obj=message,
                )
            except APIConnectionError as e:
                reply = _("Failed to communicate with endpoint!")
                log.error(f"APIConnectionError (From listener: {listener})", exc_info=e)
            except InvalidRequestError as e:
                if error := e.error:
                    # OpenAI related error, doesn't need to be restricted to bot owner only
                    reply = _("Error: {}").format(error["message"])
                    log.error(
                        f"Invalid Request Error (From listener: {listener})\nERROR: {error}",
                        exc_info=e,
                    )
                else:
                    log.error(f"Invalid Request Error (From listener: {listener})", exc_info=e)
                    return
            except AuthenticationError:
                if message.author == message.guild.owner:
                    reply = _("Invalid API key, please set a new valid key!")
                else:
                    reply = _("Uh oh, looks like my API key is invalid!")
            except RateLimitError as e:
                reply = str(e)
            except KeyError as e:
                log.debug("get_chat_response error", exc_info=e)
                await message.channel.send(_("**KeyError in prompt or system message**\n{}").format(box(str(e), "py")))
                return
            except Exception as e:
                prefix = (await self.bot.get_valid_prefixes(message.guild))[0]
                log.error(f"API Error (From listener: {listener})", exc_info=e)
                self.bot._last_exception = traceback.format_exc()
                reply = _("Uh oh, something went wrong! Bot owner can use `{}` to view the error.").format(
                    f"{prefix}traceback"
                )

        if reply is None:
            return

        files = None
        to_send = []
        if outputfile and not extract:
            # Everything to file
            file = discord.File(BytesIO(reply.encode()), filename=outputfile)
            return await message.reply(file=file, mention_author=conf.mention)
        elif outputfile and extract:
            # Code to files and text to discord
            codes = extract_code_blocks(reply)
            files = [
                discord.File(BytesIO(code.encode()), filename=f"{index + 1}_{outputfile}")
                for index, code in enumerate(codes)
            ]
            to_send.append(remove_code_blocks(reply))
        elif not outputfile and extract:
            # Everything to discord but code blocks separated
            codes = [box(code, lang) for lang, code in extract_code_blocks_with_lang(reply)]
            to_send.append(remove_code_blocks(reply))
            to_send.extend(codes)
        else:
            # Everything to discord
            to_send.append(reply)

        to_send = [str(i) for i in to_send if str(i).strip()]

        if not to_send and listener:
            return
        elif not to_send and not listener:
            return await message.reply(_("No results found"))

        for index, text in enumerate(to_send):
            if index == 0:
                await self.send_reply(message, text, conf, files, True)
            else:
                await self.send_reply(message, text, conf, None, False)

    async def get_chat_response(
        self,
        message: str,
        author: Union[discord.Member, int],
        guild: discord.Guild,
        channel: Union[discord.TextChannel, discord.Thread, discord.ForumChannel, int],
        conf: GuildSettings,
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
    ) -> str:
        conversation = self.chats.get_conversation(author)
=======
    ):
=======
        function_calls: Optional[List[dict]] = [],
=======
        function_calls: List[dict] = [],
>>>>>>> main
        function_map: Dict[str, Callable] = {},
=======
        function_calls: Optional[List[dict]] = None,
        function_map: Optional[Dict[str, Callable]] = None,
>>>>>>> main
        extend_function_calls: bool = True,
        message_obj: Optional[discord.Message] = None,
    ) -> str:
>>>>>>> main
        """Call the API asynchronously"""
        if function_calls is None:
            function_calls = []
        if function_map is None:
            function_map = {}

        if conf.use_function_calls and extend_function_calls and conf.model in SUPPORTS_FUNCTIONS:
            # Prepare registry and custom functions
            prepped_function_calls, prepped_function_map = self.db.prep_functions(
                bot=self.bot, conf=conf, registry=self.registry
            )
            function_calls.extend(prepped_function_calls)
            function_map.update(prepped_function_map)

        conversation = self.db.get_conversation(
            member_id=author if isinstance(author, int) else author.id,
            channel_id=channel if isinstance(channel, int) else channel.id,
            guild_id=guild.id,
        )
        if isinstance(author, int):
            author = guild.get_member(author)
        if isinstance(channel, int):
            channel = guild.get_channel(channel)
<<<<<<< HEAD
>>>>>>> main
        try:
            query_embedding = await request_embedding(text=message, api_key=conf.api_key)
            if not query_embedding:
                log.info(f"Could not get embedding for message: {message}")
            messages = await asyncio.to_thread(
                self.prepare_messages,
                message,
                guild,
                conf,
                conversation,
                author,
                channel,
                query_embedding,
            )
            if conf.model in CHAT:
                reply = await request_chat_response(
                    model=conf.model,
                    messages=messages,
                    temperature=conf.temperature,
                    api_key=conf.api_key,
=======

        query_embedding = []
        message_tokens = await self.get_token_count(message, conf)
        words = message.split(" ")
        if conf.top_n and message_tokens < 8191 and len(words) > 5:
            # Save on tokens by only getting embeddings if theyre enabled
            query_embedding = await self.request_embedding(message, conf)

        mem = guild.get_member(author) if isinstance(author, int) else author
        bal = humanize_number(await bank.get_balance(mem)) if mem else _("None")
        extras = {
            "banktype": "global bank" if await bank.is_global() else "local bank",
            "currency": await bank.get_currency_name(guild),
            "bank": await bank.get_bank_name(guild),
<<<<<<< HEAD
            "balance": humanize_number(
                await bank.get_balance(
                    guild.get_member(author) if isinstance(author, int) else author,
>>>>>>> main
                )
            ),
=======
            "balance": bal,
>>>>>>> main
        }

        def pop_schema(name: str, calls: List[dict]):
            return [func for func in calls if func["name"] != name]

        # Don't include if user is not a tutor
        not_tutor = [
            author.id not in conf.tutors,
            not any([role.id in conf.tutors for role in author.roles]),
        ]
        if all(not_tutor):
            if "create_memory" in function_map:
                function_calls = pop_schema("create_memory", function_calls)
                del function_map["create_memory"]

        if "edit_memory" in function_map and (not conf.embeddings or all(not_tutor)):
            function_calls = pop_schema("edit_memory", function_calls)
            del function_map["edit_memory"]

        # Don't include if there are no embeddings
        if "search_memories" in function_map and not conf.embeddings:
            function_calls = pop_schema("search_memories", function_calls)
            del function_map["search_memories"]

        max_tokens = self.get_max_tokens(conf, author)
        messages = await self.prepare_messages(
            message,
            guild,
            conf,
            conversation,
            author,
            channel,
            query_embedding,
            extras,
            function_calls,
        )
        reply = None

        calls = 0
        last_func = None
        repeats = 0
        while True:
            if calls >= conf.max_function_calls:
                function_calls = []

            if len(messages) > 1:
                # Iteratively degrade the conversation to ensure it is always under the token limit
                messages, function_calls, degraded = await self.degrade_conversation(
                    messages, function_calls, conf, author
                )
                if degraded:
                    conversation.overwrite(messages)

            if not messages:
                log.error("Messages got pruned too aggressively, increase token limit!")
                break
            try:
                response = await self.request_response(
                    messages=messages,
                    conf=conf,
                    functions=function_calls,
                    member=author,
                )
            except InvalidRequestError as e:
                log.warning(f"Function response failed. functions: {len(function_calls)}", exc_info=e)
                if await self.bot.is_owner(author) and len(function_calls) > 64:
                    dump = json.dumps(function_calls, indent=2)
                    buffer = BytesIO(dump.encode())
                    buffer.name = "FunctionDump.json"
                    buffer.seek(0)
                    file = discord.File(buffer)
                    try:
                        await channel.send(_("Too many functions called"), file=file)
                    except discord.HTTPException:
                        pass
                try:
                    response = await self.request_response(
                        messages=messages,
                        conf=conf,
                        member=author,
                    )
                except InvalidRequestError as e:
                    log.error(f"MESSAGES: {json.dumps(messages)}", exc_info=e)
                    raise e
            # except APIError as e:
            #     reply = e.user_message
            #     break
            except Exception as e:
                log.error(f"Exception occured for chat response.\nMessages: {messages}", exc_info=e)
                break

            if reply := response["content"]:
                break

            # If content is None then function call must exist
            function_call = response.get("function_call")
            if not function_call:
                continue

            calls += 1

            function_name = function_call["name"]
            if last_func is None:
                last_func = function_name
            elif last_func == function_name:
                repeats += 1
                if repeats > 4:  # Skip before calling same function a 5th time
                    log.error(f"Too many repeats: {function_name}")
                    function_calls = pop_schema(function_name, function_calls)
                    continue
            else:
                repeats = 0

            if function_name not in function_map:
                log.error(f"GPT suggested a function not provided: {function_name}")
                function_calls = pop_schema(function_name, function_calls)  # Just in case
                messages.append(
                    {
                        "role": "system",
                        "content": f"{function_name} is not a valid function name",
                    }
                )
                continue

            # Add function call to messages
            messages.append(response)
            conversation.messages.append(response)
            conversation.refresh()

            arguments = function_call.get("arguments", "{}")
            try:
                params = json.loads(arguments)
            except json.JSONDecodeError:
                params = {}
                log.error(f"Failed to parse parameters for custom function {function_name}\nArguments: {arguments}")
            # Try continuing anyway

            extras = {
                "user": guild.get_member(author) if isinstance(author, int) else author,
                "channel": guild.get_channel_or_thread(channel) if isinstance(channel, int) else channel,
                "guild": guild,
                "bot": self.bot,
                "conf": conf,
            }
            kwargs = {**params, **extras}
            func = function_map[function_name]
            try:
                if iscoroutinefunction(func):
                    func_result = await func(**kwargs)
                else:
                    func_result = await asyncio.to_thread(func, **kwargs)
            except Exception as e:
                log.error(
                    f"Custom function {function_name} failed to execute!\nArgs: {arguments}",
                    exc_info=e,
                )
                function_calls = pop_schema(function_name, function_calls)
                continue

            # Prep framework for alternative response types!
            if isinstance(func_result, dict):
                result = func_result["content"]
                file = discord.File(
                    BytesIO(func_result["file_bytes"]),
                    filename=func_result["file_name"],
                )
                try:
                    await channel.send(file=file)
                except discord.Forbidden:
                    result = "You do not have permissions to upload files in this channel"
                    function_calls = pop_schema(function_name, function_calls)

            if isinstance(func_result, bytes):
                result = func_result.decode()
            else:  # Is a string
                result = str(func_result)

            # Ensure response isnt too large
            result = await self.cut_text_by_tokens(result, conf, max_tokens)
            info = (
                f"Called function {function_name} in {guild.name} for {author.display_name}\n"
                f"Params: {params}\nResult: {result}"
            )
            log.info(info)
            messages.append({"role": "function", "name": function_name, "content": result})
            conversation.update_messages(result, "function", process_username(function_name))
            if message_obj and function_name in ["create_memory", "edit_memory"]:
                try:
                    await message_obj.add_reaction("\N{BRAIN}")
                except (discord.Forbidden, discord.NotFound):
                    pass

        # Handle the rest of the reply
        if calls > 1:
            log.info(f"Made {calls} function calls in a row")

        block = False
        if reply:
            for regex in conf.regex_blacklist:
                try:
                    reply = await self.safe_regex(regex, reply)
                except (asyncio.TimeoutError, mp.TimeoutError):
                    log.error(f"Regex {regex} in {guild.name} took too long to process. Skipping...")
                    if conf.block_failed_regex:
                        block = True
                except Exception as e:
                    log.error("Regex sub error", exc_info=e)

            conversation.update_messages(reply, "assistant", process_username(self.bot.user.name))

        if block:
            reply = _("Response failed due to invalid regex, check logs for more info.")
        conversation.cleanup(conf, author)
        return reply

    async def safe_regex(self, regex: str, content: str):
        process = self.mp_pool.apply_async(
            re.sub,
            args=(
                regex,
                "",
                content,
            ),
        )
        task = functools.partial(process.get, timeout=2)
        loop = asyncio.get_running_loop()
        new_task = loop.run_in_executor(None, task)
        subbed = await asyncio.wait_for(new_task, timeout=5)
        return subbed

    async def prepare_messages(
        self,
        message: str,
        guild: discord.Guild,
        conf: GuildSettings,
        conversation: Conversation,
        author: Optional[discord.Member],
        channel: Optional[Union[discord.TextChannel, discord.Thread, discord.ForumChannel]],
        query_embedding: List[float],
<<<<<<< HEAD:assistant/api.py
<<<<<<< HEAD
    ) -> str:
<<<<<<< HEAD
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
=======
=======
        params: dict,
        function_tokens: int,
=======
        extras: dict,
        function_calls: List[dict],
>>>>>>> main:assistant/common/chat.py
    ) -> List[dict]:
>>>>>>> main
        """Prepare content for calling the GPT API

        Args:
            message (str): question or chat message
            guild (discord.Guild): guild associated with the chat
            conf (GuildSettings): config data
            conversation (Conversation): user's conversation object for chat history
            author (Optional[discord.Member]): user chatting with the bot
            channel (Optional[Union[discord.TextChannel, discord.Thread, discord.ForumChannel]]): channel for context
            query_embedding List[float]: message embedding weights

        Returns:
            List[dict]: list of messages prepped for api
        """
        now = datetime.now().astimezone(pytz.timezone(conf.timezone))
<<<<<<< HEAD:assistant/api.py
        roles = [role for role in author.roles if "everyone" not in role.name] if author else []
        display_name = author.display_name if author else ""

        params = {
            **params,
            "botname": self.bot.user.name,
            "timestamp": f"<t:{round(now.timestamp())}:F>",
            "day": now.strftime("%A"),
            "date": now.strftime("%B %d, %Y"),
            "time": now.strftime("%I:%M %p"),
            "timetz": now.strftime("%I:%M %p %Z"),
            "members": guild.member_count,
            "username": author.name if author else "",
            "user": author.name if author else "",
            "displayname": display_name,
            "datetime": str(datetime.now()),
            "roles": humanize_list([role.name for role in roles]),
            "rolementions": humanize_list([role.mention for role in roles]),
            "avatar": author.display_avatar.url if author else "",
            "owner": guild.owner.name,
            "servercreated": f"<t:{round(guild.created_at.timestamp())}:F>",
            "server": guild.name,
            "messages": len(conversation.messages),
            "tokens": str(conversation.user_token_count(message=message)),
            "retention": str(conf.get_user_max_retention(author)),
            "retentiontime": str(conf.get_user_max_time(author)),
            "py": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "dpy": discord.__version__,
            "red": str(version_info),
            "cogs": humanize_list([self.bot.get_cog(cog).qualified_name for cog in self.bot.cogs]),
            "channelname": channel.name if channel else "",
            "channelmention": channel.mention if channel else "",
            "topic": channel.topic if channel and isinstance(channel, discord.TextChannel) else "",
        }
>>>>>>> main
        system_prompt = conf.system_prompt.format(**params)
        initial_prompt = conf.prompt.format(**params)
=======
        params = await asyncio.to_thread(get_params, self.bot, guild, now, author, channel, extras)
>>>>>>> main:assistant/common/chat.py

        def format_string(text: str):
            """Instead of format(**params) possibly giving a KeyError if prompt has code in it"""
            for k, v in params.items():
                key = "{" + k + "}"
                text = text.replace(key, str(v))
            return text

        system_prompt = format_string(conf.system_prompt)
        initial_prompt = format_string(conf.prompt)

        current_tokens = await self.get_token_count(message + system_prompt + initial_prompt, conf)
        current_tokens += await self.convo_token_count(conf, conversation)
        current_tokens += await self.function_token_count(conf, function_calls)

        max_tokens = self.get_max_tokens(conf, author)

        related = await asyncio.to_thread(conf.get_related_embeddings, query_embedding)

        embeddings = []
        # Get related embeddings (Name, text, score, dimensions)
        for i in related:
            embed_tokens = await self.get_token_count(i[1], conf)
            if embed_tokens + current_tokens > max_tokens:
                log.debug("Cannot fit anymore embeddings")
                break
            embeddings.append(i)

        if embeddings:
            results = []
            for embed in embeddings:
                entry = {"memory name": embed[0], "relatedness": embed[2], "content": embed[1]}
                results.append(entry)

            role = "function" if function_calls else "user"
            name = "search_memories" if function_calls else process_username(author.name) if author else None

            if conf.embed_method == "static":
                conversation.update_messages(json.dumps(results, indent=2), role, name)

            elif conf.embed_method == "dynamic":
                joined = "\n".join([i[1] for i in embeddings])
                initial_prompt += f"\n\n{joined}"

            else:  # Hybrid embedding
                conversation.update_messages(json.dumps(results[0], indent=2), role, name)
                if len(embeddings) > 1:
                    joined = "\n".join([i[1] for i in embeddings[1:]])
                    initial_prompt += f"\n\n{joined}"

        messages = conversation.prepare_chat(
            message,
            initial_prompt.strip(),
            system_prompt.strip(),
            name=process_username(author.name) if author else None,
        )
        return messages

    async def send_reply(
        self,
        message: discord.Message,
        content: str,
        conf: GuildSettings,
        files: Optional[List[discord.File]],
        reply: bool = False,
    ):
        embed_perms = message.channel.permissions_for(message.guild.me).embed_links
        file_perms = message.channel.permissions_for(message.guild.me).attach_files
        if files and not file_perms:
            files = []
            content += _("\nMissing 'attach files' permissions!")
        delims = ("```", "\n")

        async def send(
            content: Optional[str] = None,
            embed: Optional[discord.Embed] = None,
            embeds: Optional[List[discord.Embed]] = None,
            files: Optional[List[discord.File]] = None,
            mention: bool = False,
        ):
            if files is None:
                files = []
            if reply:
                try:
                    return await message.reply(
                        content=content,
                        embed=embed,
                        embeds=embeds,
                        files=files,
                        mention_author=mention,
                    )
                except discord.HTTPException:
                    pass
            return await message.channel.send(content=content, embed=embed, embeds=embeds, files=files)

        if len(content) <= 2000:
            await send(content, files=files, mention=conf.mention)
        elif len(content) <= 4000 and embed_perms:
            await send(embed=discord.Embed(description=content), files=files, mention=conf.mention)
        elif embed_perms:
            embeds = [discord.Embed(description=p) for p in pagify(content, page_length=3950, delims=delims)]
            for index, embed in enumerate(embeds):
                if index == 0:
                    await send(embed=embed, files=files, mention=conf.mention)
                else:
                    await send(embed=embed)
        else:
            pages = [p for p in pagify(content, page_length=2000, delims=delims)]
            for index, p in enumerate(pages):
                if index == 0:
                    await send(content=p, files=files, mention=conf.mention)
                else:
                    await send(content=p)
