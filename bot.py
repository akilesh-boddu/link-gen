import logging
import os
import asyncio
import urllib.error
import urllib.request
import json
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv, set_key

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("slipstream-deployer")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "akilesh-boddu/slipstream-fr").strip()
GITHUB_WORKFLOW = os.getenv("GITHUB_WORKFLOW", "deploy-sites.yml").strip()
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main").strip()
DEPLOY_INTERVAL_MINUTES = max(5, int(os.getenv("DEPLOY_INTERVAL_MINUTES", "60")))
ANNOUNCEMENT_CHANNEL_ID = os.getenv("ANNOUNCEMENT_CHANNEL_ID", "").strip()
GUILD_ID = os.getenv("GUILD_ID", "").strip()

SURGE_URL = os.getenv("SURGE_URL", "https://slipstream-fr.surge.sh").strip()
VERCEL_URL = os.getenv("VERCEL_URL", "https://slipstream-fr.vercel.app").strip()
CLOUDFLARE_URL = os.getenv("CLOUDFLARE_URL", "https://slipstream-fr.pages.dev").strip()

if not DISCORD_TOKEN:
    raise SystemExit("DISCORD_TOKEN is missing. Copy the template values into .env.")
if not GITHUB_TOKEN:
    raise SystemExit("GITHUB_TOKEN is missing. It needs Actions: write access to the target repository.")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


def github_request(path: str, method: str = "GET", payload: dict | None = None):
    """Call GitHub's REST API without exposing the token in logs."""
    url = f"https://api.github.com{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Slipstream-Discord-Deployment-Bot",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"GitHub API returned HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach GitHub: {exc.reason}") from None


def trigger_deployment():
    workflow = GITHUB_WORKFLOW
    if not workflow.endswith((".yml", ".yaml")):
        workflow += ".yml"
    endpoint = (
        f"/repos/{GITHUB_REPOSITORY}/actions/workflows/"
        f"{workflow}/dispatches"
    )
    status, _ = github_request(
        endpoint,
        method="POST",
        payload={"ref": GITHUB_BRANCH},
    )
    if status not in (200, 201, 202, 204):
        raise RuntimeError(f"Unexpected GitHub response: HTTP {status}")
    return datetime.now(timezone.utc)


def latest_workflow_run():
    workflow = GITHUB_WORKFLOW
    if not workflow.endswith((".yml", ".yaml")):
        workflow += ".yml"
    endpoint = (
        f"/repos/{GITHUB_REPOSITORY}/actions/workflows/"
        f"{workflow}/runs?per_page=1"
    )
    _, data = github_request(endpoint)
    runs = data.get("workflow_runs", [])
    return runs[0] if runs else None


def persist_env_value(key: str, value: str):
    """Persist the selected Discord channel in the existing .env file."""
    set_key(".env", key, value, quote_mode="never")
    os.environ[key] = value


def is_admin(interaction: discord.Interaction) -> bool:
    perms = interaction.user.guild_permissions if isinstance(interaction.user, discord.Member) else None
    return bool(perms and (perms.administrator or perms.manage_guild))


async def admin_check(interaction: discord.Interaction) -> bool:
    if not is_admin(interaction):
        await interaction.response.send_message(
            "You need **Manage Server** or **Administrator** permission to use this command.",
            ephemeral=True,
        )
        return False
    return True


class CmdsGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="cmds", description="Configure and control Slipstream deployments")

    @app_commands.command(name="setup", description="Choose the channel for hourly deployment posts")
    @app_commands.describe(channel="Text channel where the bot should post deployment links")
    async def setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not await admin_check(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message("Run this command inside your server.", ephemeral=True)
            return
        if not channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.response.send_message(
                f"I cannot send messages in {channel.mention}. Give me Send Messages and Embed Links permissions.",
                ephemeral=True,
            )
            return
        persist_env_value("ANNOUNCEMENT_CHANNEL_ID", str(channel.id))
        persist_env_value("GUILD_ID", str(interaction.guild_id))
        await interaction.response.send_message(
            f"Setup complete. Hourly deployment announcements will be posted in {channel.mention}.\n"
            f"Target repository: `{GITHUB_REPOSITORY}` (`{GITHUB_BRANCH}`).",
            ephemeral=True,
        )
        await post_status_message(
            channel,
            "🛠️ **Slipstream deployment bot configured**\n"
            "I will trigger the deployment workflow every hour and post the three permanent site links here.",
        )

    @app_commands.command(name="deploy", description="Immediately trigger all three website deployments")
    async def deploy(self, interaction: discord.Interaction):
        if not await admin_check(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await asyncio.to_thread(trigger_deployment)
            await interaction.followup.send(
                "🚀 GitHub Actions deployment workflow triggered. I'll post the links when the workflow finishes.",
                ephemeral=True,
            )
        except Exception as exc:
            log.exception("Manual deployment trigger failed")
            await interaction.followup.send(f"Deployment trigger failed: `{exc}`", ephemeral=True)

    @app_commands.command(name="status", description="Show the latest GitHub deployment workflow status")
    async def status(self, interaction: discord.Interaction):
        if not await admin_check(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            run = await asyncio.to_thread(latest_workflow_run)
            if not run:
                await interaction.followup.send("No workflow runs found yet.", ephemeral=True)
                return
            state = run.get("status", "unknown")
            conclusion = run.get("conclusion") or "in progress"
            await interaction.followup.send(
                f"**Latest deployment:** `{state}` / `{conclusion}`\n"
                f"[Open GitHub Actions run]({run.get('html_url', 'https://github.com/' + GITHUB_REPOSITORY + '/actions')})",
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.followup.send(f"Could not read workflow status: `{exc}`", ephemeral=True)

    @app_commands.command(name="pause", description="Pause hourly deployment triggers")
    async def pause(self, interaction: discord.Interaction):
        if not await admin_check(interaction):
            return
        if hourly_deploy.is_running():
            hourly_deploy.cancel()
        await interaction.response.send_message("⏸️ Hourly deployments paused. Manual `/cmds deploy` still works.", ephemeral=True)

    @app_commands.command(name="resume", description="Resume hourly deployment triggers")
    async def resume(self, interaction: discord.Interaction):
        if not await admin_check(interaction):
            return
        if not hourly_deploy.is_running():
            hourly_deploy.start()
        await interaction.response.send_message("▶️ Hourly deployments resumed.", ephemeral=True)


cmds_group = CmdsGroup()
bot.tree.add_command(cmds_group)


async def post_status_message(channel: discord.abc.Messageable, intro: str):
    embed = discord.Embed(
        title="🚀 Slipstream deployment links",
        description=intro,
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Surge.sh", value=f"[Open site]({SURGE_URL})", inline=True)
    embed.add_field(name="Vercel", value=f"[Open site]({VERCEL_URL})", inline=True)
    embed.add_field(name="Cloudflare Pages", value=f"[Open site]({CLOUDFLARE_URL})", inline=True)
    embed.set_footer(text=f"Source: {GITHUB_REPOSITORY} • branch: {GITHUB_BRANCH}")
    await channel.send(embed=embed)


async def announce_deployment(message: str):
    channel_id = os.getenv("ANNOUNCEMENT_CHANNEL_ID", "").strip()
    if not channel_id.isdigit():
        log.info("No announcement channel configured; skipping Discord announcement.")
        return
    channel = bot.get_channel(int(channel_id))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(channel_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            log.exception("Could not access configured announcement channel")
            return
    await post_status_message(channel, message)


@tasks.loop(minutes=DEPLOY_INTERVAL_MINUTES)
async def hourly_deploy():
    try:
        await asyncio.to_thread(trigger_deployment)
        await announce_deployment(
            "⏰ **Hourly deployment workflow triggered.** These are the permanent deployment addresses; "
            "the latest build may take a few minutes to finish."
        )
    except Exception:
        log.exception("Hourly deployment trigger failed")
        channel_id = os.getenv("ANNOUNCEMENT_CHANNEL_ID", "").strip()
        if channel_id.isdigit():
            channel = bot.get_channel(int(channel_id))
            if channel:
                await channel.send("⚠️ The hourly deployment could not be triggered. Check the bot logs and GitHub Actions permissions.")


@hourly_deploy.before_loop
async def before_hourly_deploy():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    log.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")
    try:
        # Global slash commands can take a little time to appear in Discord.
        synced = await bot.tree.sync()
        log.info("Synced %d application commands", len(synced))
    except discord.HTTPException:
        log.exception("Could not sync slash commands")
    if not hourly_deploy.is_running():
        hourly_deploy.start()


@bot.event
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    log.exception("Slash command error", exc_info=error)
    message = "Something went wrong while running that command. Check the bot logs."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


bot.run(DISCORD_TOKEN)
