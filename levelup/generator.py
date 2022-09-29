import logging
import os
import random
from io import BytesIO
from math import sqrt, ceil
from typing import Union

import colorgram
import requests
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from redbot.core.data_manager import bundled_data_path
from redbot.core.i18n import Translator
from redbot.core.utils.chat_formatting import humanize_number

from levelup.utils.core import Pilmoji

log = logging.getLogger("red.vrt.levelup.generator")
_ = Translator("LevelUp", __file__)
ASPECT_RATIO = (21, 9)


class Generator:
    def __init__(self):
        self.star = os.path.join(bundled_data_path(self), 'star.png')
        self.default_lvlup = os.path.join(bundled_data_path(self), 'lvlup.png')
        self.default_bg = os.path.join(bundled_data_path(self), 'card.png')
        self.default_pfp = os.path.join(bundled_data_path(self), 'defaultpfp.png')

        self.status = {
            "online": os.path.join(bundled_data_path(self), 'online.png'),
            "offline": os.path.join(bundled_data_path(self), 'offline.png'),
            "idle": os.path.join(bundled_data_path(self), 'idle.png'),
            "dnd": os.path.join(bundled_data_path(self), 'dnd.png'),
            "streaming": os.path.join(bundled_data_path(self), 'streaming.png')
        }

        self.font = os.path.join(bundled_data_path(self), 'font.ttf')

    def generate_profile(
            self,
            bg_image: str = None,
            profile_image: str = "https://i.imgur.com/sUYWCve.png",
            level: int = 1,
            user_xp: int = 0,
            next_xp: int = 100,
            user_position: str = "1",
            user_name: str = 'Unknown#0117',
            user_status: str = 'online',
            colors: dict = None,
            messages: str = "0",
            voice: str = "None",
            prestige: int = 0,
            emoji: str = None,
            stars: str = "0",
            balance: int = 0,
            currency: str = "credits",
            role_icon: str = None
    ):
        # Colors
        base = self.rand_rgb()
        namecolor = self.rand_rgb()
        statcolor = self.rand_rgb()
        lvlbarcolor = self.rand_rgb()
        # Color distancing is more strict if user hasn't defined color
        namedistance = 250
        statdistance = 250
        lvldistance = 250
        if colors:
            # Relax distance for colors that are defined
            base = colors["base"]
            if colors["name"]:
                namecolor = colors["name"]
                namedistance = 100
            if colors["stat"]:
                statcolor = colors["stat"]
                statdistance = 100
            if colors["levelbar"]:
                lvlbarcolor = colors["levelbar"]
                lvldistance = 100
            else:
                lvlbarcolor = base

        default_fill = (0, 0, 0)

        # Set canvas
        if bg_image and bg_image != "random":
            bgpath = os.path.join(bundled_data_path(self), "backgrounds")
            defaults = [i for i in os.listdir(bgpath)]
            if bg_image in defaults:
                card = Image.open(os.path.join(bgpath, bg_image))
            else:
                bg_bytes = self.get_image_content_from_url(bg_image)
                try:
                    card = Image.open(BytesIO(bg_bytes))
                except UnidentifiedImageError:
                    card = self.get_random_background()
        else:
            card = self.get_random_background()

        card = self.force_aspect_ratio(card).convert("RGBA").resize((1050, 450), Image.Resampling.LANCZOS)

        # Coord setup
        name_y = 40
        stats_y = 160
        bar_start = 450
        bar_end = 1030
        bar_top = 380
        bar_bottom = 420
        circle_x = 60
        circle_y = 75

        stroke_width = 2

        # x1, y1, x2, y2
        # Sample name box colors and make sure they're not too similar with the background
        namebox = (bar_start, name_y, bar_start + 50, name_y + 100)
        namesection = self.get_sample_section(card, namebox)
        namebg = self.get_img_color(namesection)
        namefill = default_fill
        while self.distance(namecolor, namebg) < namedistance:
            namecolor = self.rand_rgb()
        if self.distance(namefill, namecolor) < namedistance - 50:
            namefill = self.inv_rgb(namefill)

        # Sample stat box colors and make sure they're not too similar with the background
        statbox = (bar_start, stats_y, bar_start + 400, bar_top)
        statsection = self.get_sample_section(card, statbox)
        statbg = self.get_img_color(statsection)
        statstxtfill = default_fill
        while self.distance(statcolor, statbg) < statdistance:
            statcolor = self.rand_rgb()
        if self.distance(statstxtfill, statcolor) < statdistance - 50:
            statstxtfill = self.inv_rgb(statstxtfill)

        lvlbox = (bar_start, bar_top, bar_end, bar_bottom)
        lvlsection = self.get_sample_section(card, lvlbox)
        lvlbg = self.get_img_color(lvlsection)
        while self.distance(lvlbarcolor, lvlbg) < lvldistance:
            lvlbarcolor = self.rand_rgb()

        # get profile pic
        pfp_image = self.get_image_content_from_url(str(profile_image))
        if pfp_image:
            profile_bytes = BytesIO(pfp_image)
            profile = Image.open(profile_bytes)
        else:
            profile = Image.open(self.default_pfp)
        profile = profile.convert('RGBA').resize((300, 300), Image.Resampling.LANCZOS)

        # pfp border - draw at 4x and resample down to 1x for nice smooth circles
        circle_img = Image.new("RGBA", (1600, 1600))
        pfp_border = ImageDraw.Draw(circle_img)
        pfp_border.ellipse([4, 4, 1596, 1596], fill=(255, 255, 255, 0), outline=base, width=20)
        circle_img = circle_img.resize((330, 330), Image.Resampling.LANCZOS)
        card.paste(circle_img, (circle_x - 15, circle_y - 15), circle_img)

        # Mask to crop profile pic image to a circle
        # draw at 4x size and resample down to 1x for a nice smooth circle
        mask = Image.new("RGBA", ((card.size[0] * 4), (card.size[1] * 4)), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse(
            [circle_x * 4, circle_y * 4, (300 + circle_x) * 4, (300 + circle_y) * 4], fill=(255, 255, 255, 255)
        )
        mask = mask.resize(card.size, Image.Resampling.LANCZOS)

        # make a new Image to set up card-sized image for pfp layer and the circle mask for it
        profile_pic_holder = Image.new("RGBA", card.size, (255, 255, 255, 0))
        # paste on square profile pic in appropriate spot
        profile_pic_holder.paste(profile, (circle_x, circle_y))
        # make a new Image at card size to crop pfp with transparency to the circle mask
        pfp_composite_holder = Image.new("RGBA", card.size, (0, 0, 0, 0))
        pfp_composite_holder = Image.composite(profile_pic_holder, pfp_composite_holder, mask)

        # Profile image is on the background tile now
        final = Image.alpha_composite(card, pfp_composite_holder)

        # Place semi-transparent box over right side
        blank = Image.new("RGBA", card.size, (255, 255, 255, 0))
        transparent_box = Image.new("RGBA", card.size, (0, 0, 0, 100))
        blank.paste(transparent_box, (bar_start - 20, 0))
        final = Image.alpha_composite(final, blank)

        # Make the level progress bar
        progress_bar = Image.new("RGBA", (card.size[0] * 4, card.size[1] * 4), (255, 255, 255, 0))
        progress_bar_draw = ImageDraw.Draw(progress_bar)
        # Calculate data for level bar
        xp_ratio = user_xp / next_xp
        end_of_inner_bar = ((bar_end - bar_start) * xp_ratio) + bar_start
        # Rectangle 0:left x, 1:top y, 2:right x, 3:bottom y
        # Draw level bar outline
        thickness = 8
        progress_bar_draw.rounded_rectangle(
            (bar_start * 4, bar_top * 4, bar_end * 4, bar_bottom * 4),
            fill=(255, 255, 255, 0),
            outline=lvlbarcolor,
            width=thickness,
            radius=90
        )
        # Draw inner level bar 1 pixel smaller on each side
        if end_of_inner_bar > bar_start + 10:
            progress_bar_draw.rounded_rectangle(
                (bar_start * 4 + thickness, bar_top * 4 + thickness, end_of_inner_bar * 4 - thickness, bar_bottom * 4 - thickness),
                fill=lvlbarcolor,
                radius=89
            )
        progress_bar = progress_bar.resize(card.size, Image.Resampling.LANCZOS)
        # Image with level bar and pfp on background
        final = Image.alpha_composite(final, progress_bar)

        # Get status and star image and paste to profile
        blank = Image.new("RGBA", card.size, (255, 255, 255, 0))

        status = self.status[user_status] if user_status in self.status else self.status["offline"]
        status_img = Image.open(status)
        status = status_img.convert("RGBA").resize((60, 60), Image.Resampling.LANCZOS)
        star = Image.open(self.star).resize((50, 50), Image.Resampling.LANCZOS)
        # Role icon
        role_bytes = self.get_image_content_from_url(role_icon) if role_icon else None
        if role_bytes:
            role_bytes = BytesIO(role_bytes)
            role_icon_img = Image.open(role_bytes).resize((40, 40), Image.Resampling.LANCZOS)
            blank.paste(
                role_icon_img, (bar_start - 50, name_y + 10)
            )
        # Prestige icon
        prestige_bytes = self.get_image_content_from_url(emoji) if prestige else None
        if prestige_bytes:
            prestige_bytes = BytesIO(prestige_bytes)
            prestige_img = Image.open(prestige_bytes).resize((40, 40), Image.Resampling.LANCZOS)
            blank.paste(prestige_img, (bar_start - 50, bar_top))

        # Paste star and status to profile
        blank.paste(status, (circle_x + 230, circle_y + 240))
        blank.paste(star, (900, name_y + 5))

        # New final
        final = Image.alpha_composite(final, blank)

        # Stat strings
        rank = _(f"Rank: #") + str(user_position)
        leveltxt = _(f"Level: ") + str(level)
        exp = _("Exp: ") + f"{humanize_number(user_xp)}/{humanize_number(next_xp)}"
        message_count = _(f"Messages: ") + messages
        voice = _(f"Voice: ") + voice
        stars = str(stars)
        bal = _("Balance: ") + f"{humanize_number(balance)} {currency}"
        prestige_str = _(f"Prestige ") + str(prestige)

        # Setup font sizes
        draw = ImageDraw.Draw(final)

        name_size = 50
        name_font = ImageFont.truetype(self.font, name_size)
        while (name_font.getlength(user_name) + bar_start + 20) > 900:
            name_size -= 1
            name_font = ImageFont.truetype(self.font, name_size)

        stats_size = 35
        stat_offset = stats_size + 5
        stats_font = ImageFont.truetype(self.font, stats_size)

        star_font = name_font
        star_fontsize = 50
        startop = name_y
        decrement = True
        while (star_font.getlength(stars) + 960) > final.width - 10:
            star_fontsize -= 1
            if decrement:
                startop += 1
                decrement = False
            else:
                decrement = True
            star_font = ImageFont.truetype(self.font, star_fontsize)

        # Add stats text
        # Render name and credits text through pilmoji in case there are emojis
        with Pilmoji(final) as pilmoji:
            # Name text
            pilmoji.text((bar_start + 10, name_y), user_name, namecolor,
                         font=name_font,
                         stroke_width=stroke_width,
                         stroke_fill=namefill,
                         emoji_scale_factor=1.2,
                         emoji_position_offset=(0, 5))
            # Balance
            pilmoji.text((bar_start + 10, bar_top - 110), bal, statcolor,
                         font=stats_font,
                         stroke_width=stroke_width,
                         stroke_fill=statstxtfill,
                         emoji_scale_factor=1.2,
                         emoji_position_offset=(0, 5))

        # # Name text
        # draw.text((bar_start + 10, name_y), name, namecolor,
        #           font=name_font, stroke_width=stroke_width, stroke_fill=namefill)
        # # Balance
        # draw.text((bar_start + 10, bar_top - 110), bal, statcolor,
        #           font=stats_font, stroke_width=stroke_width, stroke_fill=statstxtfil)

        # Prestige
        if prestige:
            draw.text((bar_start + 10, name_y + 55), prestige_str, statcolor,
                      font=stats_font, stroke_width=stroke_width, stroke_fill=namefill)
        # Stats text
        # Rank
        draw.text((bar_start + 10, stats_y), rank, statcolor,
                  font=stats_font, stroke_width=stroke_width, stroke_fill=statstxtfill)
        # Level
        draw.text((bar_start + 10, stats_y + stat_offset), leveltxt, statcolor,
                  font=stats_font, stroke_width=stroke_width, stroke_fill=statstxtfill)
        # Messages
        draw.text((bar_start + 210 + 10, stats_y), message_count, statcolor,
                  font=stats_font, stroke_width=stroke_width, stroke_fill=statstxtfill)
        # Voice
        draw.text((bar_start + 210 + 10, stats_y + stat_offset), voice, statcolor,
                  font=stats_font, stroke_width=stroke_width, stroke_fill=statstxtfill)

        # Exp
        draw.text((bar_start + 10, bar_top - 60), exp, statcolor,
                  font=stats_font, stroke_width=stroke_width, stroke_fill=statstxtfill)

        # Stars
        draw.text((960, startop), stars, namecolor,
                  font=star_font, stroke_width=stroke_width, stroke_fill=namefill)

        return final

    def generate_slim_profile(
            self,
            bg_image: str = None,
            profile_image: str = "https://i.imgur.com/sUYWCve.png",
            level: int = 1,
            user_xp: int = 0,
            next_xp: int = 100,
            user_position: str = "1",
            user_name: str = 'Unknown#0117',
            user_status: str = 'online',
            colors: dict = None,
            messages: str = "0",
            voice: str = "None",
            prestige: int = 0,
            emoji: str = None,
            stars: str = "0",
            balance: int = 0,
            currency: str = "credits",
            role_icon: str = None
    ):
        # Colors
        base = self.rand_rgb()
        namecolor = self.rand_rgb()
        statcolor = self.rand_rgb()
        lvlbarcolor = self.rand_rgb()
        # Color distancing is more strict if user hasn't defined color
        namedistance = 250
        statdistance = 250
        lvldistance = 250
        if colors:
            # Relax distance for colors that are defined
            base = colors["base"]
            if colors["name"]:
                namecolor = colors["name"]
                namedistance = 100
            if colors["stat"]:
                statcolor = colors["stat"]
                statdistance = 100
            if colors["levelbar"]:
                lvlbarcolor = colors["levelbar"]
                lvldistance = 100
            else:
                lvlbarcolor = base

        outlinecolor = (0, 0, 0)
        text_bg = (0, 0, 0)

        # Set canvas
        aspect_ratio = (27, 7)
        if bg_image and bg_image != "random":
            bgpath = os.path.join(bundled_data_path(self), "backgrounds")
            defaults = [i for i in os.listdir(bgpath)]
            if bg_image in defaults:
                card = Image.open(os.path.join(bgpath, bg_image))
            else:
                bg_bytes = self.get_image_content_from_url(bg_image)
                try:
                    card = Image.open(BytesIO(bg_bytes))
                except UnidentifiedImageError:
                    card = self.get_random_background()
        else:
            card = self.get_random_background()

        card = self.force_aspect_ratio(card, aspect_ratio)
        card = card.convert("RGBA").resize((900, 240), Image.Resampling.LANCZOS)
        try:
            bgcolor = self.get_img_color(card)
        except Exception as e:
            log.error(f"Failed to get slim profile BG color: {e}")
            bgcolor = base

        # Compare text colors to BG
        while self.distance(namecolor, bgcolor) < namedistance:
            namecolor = self.rand_rgb()
        while self.distance(statcolor, bgcolor) < statdistance:
            statcolor = self.rand_rgb()
        while self.distance(lvlbarcolor, bgcolor) < lvldistance:
            lvlbarcolor = self.rand_rgb()
        while self.distance(outlinecolor, bgcolor) < 50:
            outlinecolor = self.rand_rgb()

        # Place semi-transparent box over right side
        blank = Image.new("RGBA", card.size, (255, 255, 255, 0))
        transparent_box = Image.new("RGBA", card.size, (0, 0, 0, 100))
        blank.paste(transparent_box, (240, 0))
        card = Image.alpha_composite(card, blank)

        # Draw
        draw = ImageDraw.Draw(card)

        # Editing stuff here
        # ======== Fonts to use =============
        font_normal = ImageFont.truetype(self.font, 40)
        font_small = ImageFont.truetype(self.font, 25)

        def get_str(xp):
            return "{:,}".format(xp)

        rank = _(f"Rank: #{user_position}")
        level = _(f"Level: {level}")
        exp = f"Exp: {get_str(user_xp)}/{get_str(next_xp)}"
        messages = _(f"Messages: {messages}")
        voice = _(f"Voice Time: {voice}")
        name = f"{user_name}"
        if prestige:
            name += _(f" - Prestige {prestige}")
        stars = str(stars)

        # stat text
        draw.text((260, 20), name, namecolor, font=font_normal, stroke_width=1, stroke_fill=text_bg)
        draw.text((260, 95), rank, statcolor, font=font_small, stroke_width=1, stroke_fill=text_bg)
        draw.text((260, 125), level, statcolor, font=font_small, stroke_width=1, stroke_fill=text_bg)
        draw.text((260, 160), exp, statcolor, font=font_small, stroke_width=1, stroke_fill=text_bg)
        draw.text((465, 95), messages, statcolor, font=font_small, stroke_width=1, stroke_fill=text_bg)
        draw.text((465, 125), voice, statcolor, font=font_small, stroke_width=1, stroke_fill=text_bg)

        # STAR TEXT
        if len(str(stars)) < 3:
            star_font = ImageFont.truetype(self.font, 35)
            draw.text((825, 25), stars, statcolor, font=star_font, stroke_width=1, stroke_fill=text_bg)
        else:
            star_font = ImageFont.truetype(self.font, 30)
            draw.text((825, 28), stars, statcolor, font=star_font, stroke_width=1, stroke_fill=text_bg)

        # Adding another blank layer for the progress bar
        progress_bar = Image.new("RGBA", card.size, (255, 255, 255, 0))
        progress_bar_draw = ImageDraw.Draw(progress_bar)
        bar_start = 260
        bar_end = 740
        # rectangle 0:x, 1:top y, 2:length, 3:bottom y
        progress_bar_draw.rectangle((bar_start, 200, bar_end, 215), fill=(255, 255, 255, 0), outline=lvlbarcolor)

        xp_ratio = user_xp / next_xp
        end_of_inner_bar = ((bar_end - bar_start) * xp_ratio) + bar_start

        progress_bar_draw.rectangle((bar_start + 2, 203, end_of_inner_bar - 2, 212), fill=statcolor)

        # pfp border - draw at 4x and resample down to 1x for nice smooth circles
        circle_img = Image.new("RGBA", (800, 800))
        pfp_border = ImageDraw.Draw(circle_img)
        pfp_border.ellipse([4, 4, 796, 796], fill=(255, 255, 255, 0), outline=base, width=12)
        circle_img = circle_img.resize((200, 200), Image.Resampling.LANCZOS)
        card.paste(circle_img, (19, 19), circle_img)

        # get profile pic
        pfp_image = self.get_image_content_from_url(str(profile_image))
        if pfp_image:
            profile_bytes = BytesIO(pfp_image)
            profile = Image.open(profile_bytes)
        else:
            profile = Image.open(self.default_pfp)

        profile = profile.convert('RGBA').resize((180, 180), Image.Resampling.LANCZOS)

        # Mask to crop profile pic image to a circle
        # draw at 4x size and resample down to 1x for a nice smooth circle
        mask = Image.new("RGBA", ((card.size[0] * 4), (card.size[1] * 4)), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((116, 116, 836, 836), fill=(255, 255, 255, 255))
        mask = mask.resize(card.size, Image.Resampling.LANCZOS)

        # make a new Image to set up card-sized image for pfp layer and the circle mask for it
        profile_pic_holder = Image.new("RGBA", card.size, (255, 255, 255, 0))

        # paste on square profile pic in appropriate spot
        profile_pic_holder.paste(profile, (29, 29, 209, 209))

        # make a new Image at card size to crop pfp with transparency to the circle mask
        pfp_composite_holder = Image.new("RGBA", card.size, (0, 0, 0, 0))
        pfp_composite_holder = Image.composite(profile_pic_holder, pfp_composite_holder, mask)

        # layer the pfp_composite_holder onto the card
        pre = Image.alpha_composite(card, pfp_composite_holder)
        # layer on the progress bar
        pre = Image.alpha_composite(pre, progress_bar)

        status = self.status[user_status] if user_status in self.status else self.status["offline"]
        status_img = Image.open(status)
        status = status_img.convert("RGBA").resize((40, 40), Image.Resampling.LANCZOS)
        rep_icon = Image.open(self.star)
        rep_icon = rep_icon.convert("RGBA").resize((40, 40), Image.Resampling.LANCZOS)

        blank = Image.new("RGBA", pre.size, (255, 255, 255, 0))
        blank.paste(status, (500, 50))

        # Status badge
        # Another blank
        blank = Image.new("RGBA", pre.size, (255, 255, 255, 0))
        blank.paste(status, (169, 169))
        # Add rep star
        blank.paste(rep_icon, (780, 29))

        final = Image.alpha_composite(pre, blank)
        return final

    def generate_levelup(
            self,
            bg_image: str = None,
            profile_image: str = None,
            level: int = 1,
            color: tuple = (0, 0, 0),
    ):
        if bg_image and bg_image != "random":
            bgpath = os.path.join(bundled_data_path(self), "backgrounds")
            defaults = [i for i in os.listdir(bgpath)]
            if bg_image in defaults:
                card = Image.open(os.path.join(bgpath, bg_image))
            else:
                bg_bytes = self.get_image_content_from_url(bg_image)
                try:
                    card = Image.open(BytesIO(bg_bytes))
                except UnidentifiedImageError:
                    card = self.get_random_background()
        else:
            card = self.get_random_background()

        card_size = (180, 60)
        aspect_ratio = (18, 6)
        card = self.force_aspect_ratio(card, aspect_ratio).convert("RGBA")
        card = card.resize(card_size, Image.Resampling.LANCZOS)

        fillcolor = (0, 0, 0)
        txtcolor = color
        # Draw rounded rectangle at 4x size and scale down to crop card to
        mask = Image.new("RGBA", ((card.size[0] * 4), (card.size[1] * 4)), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle(
            (0, 0, card.size[0] * 4, card.size[1] * 4),
            fill=fillcolor,
            width=2,
            radius=120
        )
        mask = mask.resize(card.size, Image.Resampling.LANCZOS)

        # Make new Image to create composite
        composite_holder = Image.new("RGBA", card.size, (0, 0, 0, 0))
        card = Image.composite(card, composite_holder, mask)

        # Prep profile to paste
        pfp_image = self.get_image_content_from_url(str(profile_image))
        if pfp_image:
            profile_bytes = BytesIO(pfp_image)
            profile = Image.open(profile_bytes)
        else:
            profile = Image.open(self.default_pfp)
        profile = profile.convert('RGBA').resize((60, 60), Image.Resampling.LANCZOS)

        # Create mask for profile image crop
        mask = Image.new("RGBA", ((card.size[0] * 4), (card.size[1] * 4)), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, 60 * 4, 60 * 4), fill=fillcolor)
        mask = mask.resize(card.size, Image.Resampling.LANCZOS)

        pfp_holder = Image.new("RGBA", card.size, (255, 255, 255, 0))
        pfp_holder.paste(profile, (0, 0))

        pfp_composite_holder = Image.new("RGBA", card.size, (0, 0, 0, 0))
        pfp_composite_holder = Image.composite(pfp_holder, pfp_composite_holder, mask)

        final = Image.alpha_composite(card, pfp_composite_holder)

        string = _("Level ") + str(level)
        fontsize = 24
        if len(str(level)) > 2:
            fontsize = 19

        # Draw
        draw = ImageDraw.Draw(final)

        if len(str(level)) > 2:
            size = 19
        else:
            size = 24
        font = ImageFont.truetype(self.font, size)

        # Filling text
        text_x = 65
        text_y = int((card.size[1] / 2) - (fontsize / 1.4))
        draw.text((text_x, text_y), string, txtcolor, font=font, stroke_width=1, stroke_fill=fillcolor)
        return final

    def get_all_backgrounds(self):
        backgrounds = os.path.join(bundled_data_path(self), "backgrounds")
        choices = os.listdir(backgrounds)
        if not choices:
            return None
        imgs = []
        for filename in choices:
            filepath = os.path.join(backgrounds, filename)
            img = self.force_aspect_ratio(Image.open(filepath))
            img = img.convert("RGBA").resize((1050, 450), Image.Resampling.LANCZOS)
            draw = ImageDraw.Draw(img)
            ext_replace = [".png", ".jpg", ".jpeg", ".webp", ".gif"]
            txt = filename
            for ext in ext_replace:
                txt = txt.replace(ext, "")
            draw.text((10, 10), txt, font=ImageFont.truetype(self.font, 100))
            if not img:
                log.error(f"Failed to load image for default background '{filename}`")
                continue
            imgs.append((img, filename))

        # Sort by name
        imgs = sorted(imgs, key=lambda key: key[1])

        # Make grid 4 wide by however many tall
        rowcount = ceil(len(imgs) / 4)
        # Make a bunch of rows of 4
        rows = []
        index = 0
        for i in range(rowcount):
            first = None
            final = None
            for x in range(4):
                if index >= len(imgs):
                    continue
                img_obj = imgs[index][0]
                index += 1
                if first is None:
                    first = img_obj
                    continue
                if final is None:
                    final = self.concat_img_h(first, img_obj)
                else:
                    final = self.concat_img_h(final, img_obj)
            rows.append(final)

        # Now concat the rows vertically
        first = None
        final = None
        for row_img_obj in rows:
            if row_img_obj is None:
                continue
            if first is None:
                first = row_img_obj
                continue
            if final is None:
                final = self.concat_img_v(first, row_img_obj)
            else:
                final = self.concat_img_v(final, row_img_obj)

        return final

    @staticmethod
    def concat_img_v(im1: Image, im2: Image) -> Image:
        new = Image.new("RGBA", (im1.width, im1.height + im2.height))
        new.paste(im1, (0, 0))
        new.paste(im2, (0, im1.height))
        return new

    @staticmethod
    def concat_img_h(im1: Image, im2: Image) -> Image:
        new = Image.new("RGBA", (im1.width + im2.width, im1.height))
        new.paste(im1, (0, 0))
        new.paste(im2, (im1.width, 0))
        return new

    @staticmethod
    def get_image_content_from_url(url: str) -> Union[bytes, None]:
        try:
            res = requests.get(url)
            return res.content
        except Exception as e:
            log.error(f"Failed to get image from url: {url}\nError: {e}", exc_info=True)
            return None

    @staticmethod
    def get_img_color(img: Union[Image.Image, str, bytes, BytesIO]) -> tuple:
        try:
            colors = colorgram.extract(img, 1)
            return colors[0].rgb
        except Exception as e:
            log.warning(f"Failed to get image color: {e}")
            return 0, 0, 0

    @staticmethod
    def distance(color: tuple, background_color: tuple) -> float:
        # Values
        x1, y1, z1 = color
        x2, y2, z2 = background_color

        # Distances
        dx = x1 - x2
        dy = y1 - y2
        dz = z1 - z2

        # Final distance
        return sqrt(dx ** 2 + dy ** 2 + dz ** 2)

    @staticmethod
    def inv_rgb(rgb: tuple) -> tuple:
        new_rgb = (255 - rgb[0], 255 - rgb[1], 255 - rgb[2])
        return new_rgb

    @staticmethod
    def rand_rgb() -> tuple:
        r = random.randint(0, 256)
        g = random.randint(0, 256)
        b = random.randint(0, 256)
        return r, g, b

    @staticmethod
    def get_sample_section(image: Image, box: tuple) -> Image:
        # x1, y1, x2, y2
        return image.crop((box[0], box[1], box[2], box[3]))

    @staticmethod
    def force_aspect_ratio(image: Image, aspect_ratio: tuple = ASPECT_RATIO) -> Image:
        x, y = aspect_ratio
        w, h = image.size
        new_res = []
        for i in range(1, 10000):
            nw = i * x
            nh = i * y
            if not new_res:
                new_res = [nw, nh]
            elif nw <= w and nh <= h:
                new_res = [nw, nh]
            else:
                break
        x_split = int((w - new_res[0]) / 2)
        x1 = x_split
        x2 = w - x_split
        y_split = int((h - new_res[1]) / 2)
        y1 = y_split
        y2 = h - y_split
        box = (x1, y1, x2, y2)
        cropped = image.crop(box)
        return cropped

    def get_random_background(self) -> Image:
        bg_dir = os.path.join(bundled_data_path(self), "backgrounds")
        choice = random.choice(os.listdir(bg_dir))
        bg_file = os.path.join(bg_dir, choice)
        return Image.open(bg_file)

    @staticmethod
    def has_emoji(text: str) -> Union[str, bool]:
        if text.count(":") < 2:
            return False
        if "<" in text:
            return "custom"
        else:
            return "unicode"
