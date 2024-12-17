import asyncpg
from redbot.core import commands
from redbot.core.utils.chat_formatting import box, pagify

from ..abc import MixinMeta
from ..engine import engine
from ..views.postgres_creds import SetConnectionView


class Admin(MixinMeta):
    @commands.group(name="clickerset", aliases=["cowclicker"])
    @commands.is_owner()
    async def clickerset(self, ctx: commands.Context):
        """Cow Clicker settings

        **Base Commands**
        - `[p]click` - Start a Cow Clicker session
        - `[p]clicks [@user=Yourself]` - Show the number of clicks you have, or another user if specified
        - `[p]topclickers [show_global=False]` - Show the top clickers, optionally show global top clickers

        Use `[p]help CowClicker` to view the cog help and version (Case sensitive)
        """

    @clickerset.command(name="postgres")
    async def clickerset_postgres(self, ctx: commands.Context):
        """Set the Postgres connection info"""
        await SetConnectionView(self, ctx).start()

    @clickerset.command(name="nukedb")
    async def clickerset_nukedb(self, ctx: commands.Context, confirm: bool):
        """Delete the database for this cog and reinitialize it

        THIS CANNOT BE UNDONE!"""
        if not confirm:
            return await ctx.send(f"You must confirm this action with `{ctx.clean_prefix}clickerset nukedb True`")
        config = await self.bot.get_shared_api_tokens("postgres")
        if not config:
            return await ctx.send(f"Postgres credentials not set! Use `{ctx.clean_prefix}clickerset postgres` command!")

        conn = None
        try:
            try:
                conn = await asyncpg.connect(**config)
            except asyncpg.InvalidPasswordError:
                return await ctx.send("Invalid password!")
            except asyncpg.InvalidCatalogNameError:
                return await ctx.send("Invalid database name!")
            except asyncpg.InvalidAuthorizationSpecificationError:
                return await ctx.send("Invalid user!")

            await conn.execute("DROP DATABASE IF EXISTS cowclicker")
        finally:
            if conn:
                await conn.close()

        await self.initialize()
        await ctx.send("Database has been nuked and reinitialized")

    @clickerset.command(name="diagnose")
    async def clickerset_diagnose(self, ctx: commands.Context):
        """Check the database connection"""
        config = await self.bot.get_shared_api_tokens("postgres")
        if not config:
            return await ctx.send(f"Postgres credentials not set! Use `{ctx.clean_prefix}clickerset postgres` command!")
        issues = await engine.diagnose_issues(self, config)
        for p in pagify(issues, page_length=1980):
            await ctx.send(box(p, lang="python"))
