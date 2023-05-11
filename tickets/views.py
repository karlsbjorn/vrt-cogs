import asyncio
import contextlib
import logging
import traceback
from datetime import datetime
from typing import Dict, Optional, Union

import discord
import numpy as np
from discord import ButtonStyle, Interaction, TextStyle
from discord.ui import Button, Modal, TextInput, View
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator
from redbot.core.utils.chat_formatting import box, humanize_list, pagify

from .utils import update_active_overview

_ = Translator("SupportViews", __file__)
log = logging.getLogger("red.vrt.supportview")


async def wait_reply(
    ctx: commands.Context,
    timeout: Optional[int] = 60,
    delete: Optional[bool] = True,
) -> Optional[str]:
    def check(message: discord.Message):
        return message.author == ctx.author and message.channel == ctx.channel

    try:
        reply = await ctx.bot.wait_for("message", timeout=timeout, check=check)
        res = reply.content
        if delete:
            with contextlib.suppress(
                discord.HTTPException, discord.NotFound, discord.Forbidden
            ):
                await reply.delete(delay=10)
        if res.lower().strip() == _("cancel"):
            return None
        return res.strip()
    except asyncio.TimeoutError:
        return None


def get_color(color: str) -> ButtonStyle:
    if color == "red":
        style = ButtonStyle.red
    elif color == "blue":
        style = ButtonStyle.blurple
    elif color == "green":
        style = ButtonStyle.green
    else:
        style = ButtonStyle.grey
    return style


def get_modal_style(style: str) -> TextStyle:
    if style == "short":
        style = TextStyle.short
    elif style == "long":
        style = TextStyle.long
    else:
        style = TextStyle.paragraph
    return style


class Confirm(View):
    def __init__(self, ctx):
        self.ctx = ctx
        self.value = None
        super().__init__(timeout=60)

    async def interaction_check(self, interaction: Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                content=_("You are not allowed to interact with this button."),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Yes", style=ButtonStyle.green)
    async def confirm(self, interaction: Interaction, button: Button):
        if not await self.interaction_check(interaction):
            return
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="No", style=ButtonStyle.red)
    async def cancel(self, interaction: Interaction, button: Button):
        if not await self.interaction_check(interaction):
            return
        self.value = False
        await interaction.response.defer()
        self.stop()


async def confirm(ctx, msg: discord.Message):
    try:
        view = Confirm(ctx)
        await msg.edit(view=view)
        await view.wait()
        if view.value is None:
            await msg.delete()
        else:
            await msg.edit(view=None)
        return view.value
    except Exception as e:
        log.warning(f"Confirm Error: {e}")
        return None


class TestButton(View):
    def __init__(
        self,
        style: str = "grey",
        label: str = "Button Test",
        emoji: Union[discord.Emoji, discord.PartialEmoji, str] = None,
    ):
        super().__init__()
        style = get_color(style)
        butt = discord.ui.Button(label=label, style=style, emoji=emoji)
        self.add_item(butt)


class TicketModal(Modal):
    def __init__(self, title: str, data: dict):
        super().__init__(
            title=_("{} Ticket").format(title.upper()), timeout=300
        )
        self.fields = {}
        self.inputs: Dict[str, TextInput] = {}
        for key, info in data.items():
            field = TextInput(
                label=info["label"],
                style=get_modal_style(info["style"]),
                placeholder=info["placeholder"],
                default=info["default"],
                required=info["required"],
                min_length=info["min_length"],
                max_length=info["max_length"],
            )
            self.add_item(field)
            self.inputs[key] = field

    async def on_submit(self, interaction: discord.Interaction):
        for k, v in self.inputs.items():
            self.fields[k] = {"question": v.label, "answer": v.value}
        await interaction.response.defer()


class SupportButton(Button):
    def __init__(self, panel: dict):
        super().__init__(
            style=get_color(panel["button_color"]),
            label=panel["button_text"],
            custom_id=panel["name"],
            emoji=panel["button_emoji"],
            row=panel.get("row"),
        )
        self.panel_name = panel["name"]

    async def callback(self, interaction: Interaction):
        try:
            await self.create_ticket(interaction)
        except Exception as e:
            log.error(
                f"Failed to create ticket in {interaction.guild.name}: {e}\n"
                f"TRACEBACK\n"
                f"{traceback.format_exc()}"
            )

    async def create_ticket(self, interaction: Interaction):
        guild = interaction.guild
        user = interaction.user
        roles = [r.id for r in user.roles]
        conf = await self.view.config.guild(guild).all()
        blacklist = conf["blacklist"]
        for rid_uid in blacklist:
            if rid_uid == user.id:
                em = discord.Embed(
                    description=_(
                        "You been blacklisted from creating tickets!"
                    ),
                    color=discord.Color.red(),
                )
                return await interaction.response.send_message(
                    embed=em, ephemeral=True
                )
            elif rid_uid in roles:
                em = discord.Embed(
                    description=_(
                        "You have a role that has been blacklisted from creating tickets!"
                    ),
                    color=discord.Color.red(),
                )
                return await interaction.response.send_message(
                    embed=em, ephemeral=True
                )

        panel = conf["panels"][self.panel_name]
        max_tickets = conf["max_tickets"]
        opened = conf["opened"]
        user_can_close = conf["user_can_close"]
        logchannel = (
            guild.get_channel(panel["log_channel"])
            if panel["log_channel"]
            else None
        )
        uid = str(user.id)
        if uid in opened and max_tickets <= len(opened[uid]):
            em = discord.Embed(
                description=_(
                    "You have the maximum amount of tickets opened already!"
                ),
                color=discord.Color.red(),
            )
            return await interaction.response.send_message(
                embed=em, ephemeral=True
            )
        category = (
            guild.get_channel(panel["category_id"])
            if panel["category_id"]
            else None
        )
        if not category:
            em = discord.Embed(
                description=_(
                    "The category for this support panel cannot be found!\n"
                    "please contact an admin!"
                ),
                color=discord.Color.red(),
            )
            return await interaction.response.send_message(
                embed=em, ephemeral=True
            )

        # Throw modal before creating ticket if the panel has one
        form_embed = discord.Embed()
        modal = panel.get("modal")
        answers = {}
        has_response = False
        if modal:
            title = _("Submission Info")
            form_embed = discord.Embed(color=user.color)
            if user.avatar:
                form_embed.set_author(name=title, icon_url=user.avatar.url)
            else:
                form_embed.set_author(name=title)
            m = TicketModal(self.panel_name, modal)
            await interaction.response.send_modal(m)
            await m.wait()

            if not m.fields:
                return await interaction.response.defer()

            for submission_info in m.fields.values():
                question = submission_info["label"]
                answer = submission_info["answer"]
                if not answer:
                    answer = _("Unanswered")
                else:
                    has_response = True

                answers[question] = answer

                if len(answer) <= 1024:
                    form_embed.add_field(
                        name=question, value=answer, inline=False
                    )
                    continue

                chunks = [ans for ans in pagify(answer, page_length=1024)]
                for index, chunk in enumerate(chunks):
                    form_embed.add_field(
                        name=f"{question} ({index + 1})",
                        value=chunk,
                        inline=False,
                    )

        can_read_send = discord.PermissionOverwrite(
            read_messages=True, send_messages=True, attach_files=True
        )
        read_and_manage = discord.PermissionOverwrite(
            read_messages=True, send_messages=True, manage_channels=True
        )

        support_roles = []
        support_mentions = []
        panel_roles = []
        panel_mentions = []
        for role_id, mention_toggle in conf["support_roles"]:
            role = guild.get_role(role_id)
            if not role:
                continue
            support_roles.append(role)
            if mention_toggle:
                support_mentions.append(role.mention)
        for role_id, mention_toggle in panel.get("roles", []):
            role = guild.get_role(role_id)
            if not role:
                continue
            panel_roles.append(role)
            if mention_toggle:
                panel_mentions.append(role.mention)

        support_roles.extend(panel_roles)
        support_mentions.extend(panel_mentions)

        overwrite = {
            guild.default_role: discord.PermissionOverwrite(
                read_messages=False
            ),
            guild.me: read_and_manage,
            user: can_read_send,
        }
        for role in support_roles:
            overwrite[role] = can_read_send

        num = panel["ticket_num"]
        now = datetime.now().astimezone()
        name_fmt = panel["ticket_name"]
        params = {
            "num": str(num),
            "user": user.name,
            "displayname": user.display_name,
            "id": str(user.id),
            "shortdate": now.strftime("%m-%d"),
            "longdate": now.strftime("%m-%d-%Y"),
            "time": now.strftime("%I-%M-%p"),
        }
        channel_name = name_fmt.format(**params) if name_fmt else user.name
        try:
            if panel.get("threads"):
                channel = interaction.channel
                if alt_cid := panel.get("alt_channel"):
                    alt_channel = guild.get_channel(alt_cid)
                    if alt_channel and isinstance(
                        alt_channel, discord.TextChannel
                    ):
                        channel = alt_channel
                archive = round(conf["inactive"] * 60)
                arr = np.asarray([60, 1440, 4320, 10080])
                index = (np.abs(arr - archive)).argmin()
                auto_archive_duration = int(arr[index])

                reason = _("{} ticket for {}").format(
                    self.panel_name, str(interaction.user)
                )
                channel_or_thread: discord.Thread = (
                    await channel.create_thread(
                        name=channel_name,
                        auto_archive_duration=auto_archive_duration,
                        reason=reason,
                        invitable=conf["user_can_manage"],
                    )
                )
                await channel_or_thread.add_user(interaction.user)
                if conf["auto_add"] and not support_mentions:
                    for role in support_roles:
                        for member in role.members:
                            await channel_or_thread.add_user(member)
            else:
                if alt_cid := panel.get("alt_channel"):
                    alt_channel = guild.get_channel(alt_cid)
                    if alt_channel and isinstance(
                        alt_channel, discord.CategoryChannel
                    ):
                        category = alt_channel
                    elif alt_channel and isinstance(
                        alt_channel, discord.TextChannel
                    ):
                        if alt_channel.category:
                            category = alt_channel.category
                channel_or_thread = await category.create_text_channel(
                    channel_name, overwrites=overwrite
                )
        except Exception as e:
            em = discord.Embed(
                description=_(
                    "There was an error while preparing your ticket, please contact an admin!\n{}"
                ).format(box(str(e), "py")),
                color=discord.Color.red(),
            )
            if modal:
                return await interaction.followup.send(
                    embed=em, ephemeral=True
                )
            else:
                return await interaction.response.send_message(
                    embed=em, ephemeral=True
                )

        prefix = (await self.view.bot.get_valid_prefixes(self.view.guild))[0]
        default_message = (
            _("Welcome to your ticket channel ") + f"{user.display_name}!"
        )
        if user_can_close:
            default_message += _(
                "\nYou or an admin can close this with the `{}close` command"
            ).format(prefix)

        messages = panel["ticket_messages"]
        params = {
            "username": user.name,
            "displayname": user.display_name,
            "mention": user.mention,
            "id": str(user.id),
        }
        content = "" if panel.get("threads") else user.mention
        if support_mentions:
            if not panel.get("threads"):
                support_mentions.append(user.mention)
            content = humanize_list(support_mentions)

        allowed_mentions = discord.AllowedMentions(roles=True)
        if messages:
            embeds = []
            for einfo in messages:
                em = discord.Embed(
                    title=einfo["title"].format(**params)
                    if einfo["title"]
                    else None,
                    description=einfo["desc"].format(**params),
                    color=user.color,
                )
                if einfo["footer"]:
                    em.set_footer(text=einfo["footer"].format(**params))
                embeds.append(em)

            msg = await channel_or_thread.send(
                content=content,
                embeds=embeds,
                allowed_mentions=allowed_mentions,
            )
        else:
            em = discord.Embed(description=default_message, color=user.color)
            if user.avatar:
                em.set_thumbnail(url=user.avatar.url)
            msg = await channel_or_thread.send(
                content=content, embed=em, allowed_mentions=allowed_mentions
            )

        if len(form_embed.fields) > 0:
            await channel_or_thread.send(embed=form_embed)

        desc = _(
            "Your ticket channel has been created, **[CLICK HERE]({})**"
        ).format(msg.jump_url)
        em = discord.Embed(description=desc, color=user.color)
        if modal:
            with contextlib.suppress(discord.HTTPException):
                await interaction.followup.send(embed=em, ephemeral=True)
        else:
            await interaction.response.send_message(embed=em, ephemeral=True)

        if logchannel:
            ts = int(now.timestamp())
            desc = _(
                "`Created By: `{}\n"
                "`User ID:    `{}\n"
                "`Opened:     `{}\n"
                "`Ticket:     `{}\n"
                "`Panel Name: `{}\n"
                "**[Click to Jump!]({})**"
            ).format(
                str(user),
                user.id,
                f"<t:{ts}:R>",
                channel_name,
                self.panel_name,
                msg.jump_url,
            )
            em = discord.Embed(
                title=_("Ticket Opened"),
                description=desc,
                color=discord.Color.red(),
            )
            if user.avatar:
                em.set_thumbnail(url=user.avatar.url)

            for question, answer in answers.items():
                em.add_field(
                    name=f"__{question}__", value=answer, inline=False
                )

            view = LogView(guild, channel_or_thread)
            log_message = await logchannel.send(embed=em, view=view)
        else:
            log_message = None

        async with self.view.config.guild(guild).all() as conf:
            conf["panels"][self.panel_name]["ticket_num"] += 1
            if uid not in conf["opened"]:
                conf["opened"][uid] = {}
            conf["opened"][uid][str(channel_or_thread.id)] = {
                "panel": self.panel_name,
                "opened": now.isoformat(),
                "pfp": str(user.avatar.url) if user.avatar else None,
                "logmsg": log_message.id if log_message else None,
                "answers": answers,
                "has_response": has_response,
            }

            new_id = await update_active_overview(guild, conf)
            if new_id:
                conf["overview_msg"] = new_id


class PanelView(View):
    def __init__(
        self,
        bot: Red,
        guild: discord.Guild,
        config: Config,
        panels: list,  # List of support panels that have the same message/channel ID
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild = guild
        self.config = config
        self.panels = panels

    async def start(self):
        for panel in self.panels:
            self.add_item(SupportButton(panel))
        chan = self.guild.get_channel(self.panels[0]["channel_id"])
        message = await chan.fetch_message(self.panels[0]["message_id"])
        await message.edit(view=self)


class LogView(View):
    def __init__(
        self,
        guild: discord.Guild,
        channel: Union[discord.TextChannel, discord.Thread],
    ):
        super().__init__(timeout=None)
        self.guild = guild
        self.channel = channel
        self.added = set()

    @discord.ui.button(label="Join Ticket", style=ButtonStyle.green)
    async def join_ticket(self, interaction: Interaction, button: Button):
        user = interaction.user
        if user.id in self.added:
            return await interaction.response.send_message(
                _("You have already been added to the ticket **{}**!").format(
                    self.channel.name
                ),
                ephemeral=True,
                delete_after=60,
            )
        perms = [
            self.channel.permissions_for(user).view_channel,
            self.channel.permissions_for(user).send_messages,
        ]
        if isinstance(self.channel, discord.TextChannel):
            if all(perms):
                return await interaction.response.send_message(
                    _("You already have access to the ticket **{}**!").format(
                        self.channel.name
                    ),
                    ephemeral=True,
                    delete_after=60,
                )
            await self.channel.set_permissions(
                user, read_messages=True, send_messages=True
            )
            await self.channel.send(
                _("{} was added to the ticket").format(str(user))
            )
        else:
            await self.channel.add_user(user)
        self.added.add(user.id)
        await interaction.response.send_message(
            _("You have been added to the ticket **{}**").format(
                self.channel.name
            ),
            ephemeral=True,
            delete_after=60,
        )
