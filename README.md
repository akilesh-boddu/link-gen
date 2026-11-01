Slipstream Deployment Bot
A small Python Discord bot that triggers the existing GitHub Actions deployment workflow for:
- Surge: https://slipstream-fr.surge.sh
- Vercel: https://slipstream-fr.vercel.app (change this in .env if your Vercel domain differs)
- Cloudflare Pages: https://slipstream-fr.pages.dev
Target repository: https://github.com/akilesh-boddu/slipstream-fr
What it does
- /cmds setup channel:#channel — choose the Discord channel for announcements.
- /cmds deploy — manually trigger the GitHub Actions workflow.
- /cmds status — show the latest workflow run.
- /cmds pause — pause hourly triggers.
- /cmds resume — resume hourly triggers.
- Triggers the workflow every 60 minutes while the bot process is running.
The bot does not build or host the site itself. It calls the repository's existing
.github/workflows/deploy-sites.yml workflow using GitHub's workflow-dispatch API.
That workflow must already be configured with its Surge, Vercel, and Cloudflare
Actions secrets. The permanent domains must also be configured in those hosting
projects. The bot cannot create or guarantee provider domains simply by posting URLs.
Requirements
- Python 3.10 or newer.
- A Discord application and bot.
- A GitHub token with Actions: read and write permission for
  akilesh-boddu/slipstream-fr.
- The repository's existing deployment workflow enabled.
- An always-on Python host or computer. If the process stops, hourly scheduling stops.
Install
python -m venv .venv
Activate the virtual environment:

Windows:
.venv\Scripts\activate
macOS/Linux:
source .venv/bin/activate
Install dependencies:
pip install -r requirements.txt
Configure .env
Open .env and replace:
- DISCORD_TOKEN with your bot token.
- GITHUB_TOKEN with a fine-grained GitHub token restricted to this repository,
  granting Actions read/write access.
Do not paste tokens into Discord, screenshots, chat, or GitHub. Do not commit .env.
If a token is exposed, revoke it and create a replacement.

Check VERCEL_URL against the actual production domain in your Vercel project.
The example is only a default; it is not proof that the domain has been claimed.
Discord setup
1. In the Discord Developer Portal, create an application and add a bot.
2. Invite it to your server with the bot and applications.commands scopes.
3. Give it permission to View Channels, Send Messages, and Embed Links in the
   announcement channel.
4. Start the bot:
python bot.py
5. In your server, run /cmds setup and select the announcement channel.
6. Run /cmds deploy to test the workflow.
7. Use /cmds status to inspect the latest GitHub Actions run.
Slash commands are synced globally and may take a little while to appear.

Only server members with Manage Server or Administrator permission can
run the configuration and deployment commands.
Important deployment notes
- The workflow filename defaults to deploy-sites.yml, branch main.
- The GitHub Actions workflow must contain a workflow_dispatch trigger.
- Add the provider credentials as GitHub repository Actions secrets, not to this
  bot's .env.
- Surge and Cloudflare Pages serve static files. The source project's Node backend
  must remain hosted separately for backend-dependent features.
- The bot posts the stable domain addresses after triggering a run. A trigger is
  not the same as a successful build; use /cmds status and the GitHub Actions
  run link to verify completion.
- Hourly deployment triggers are not the same as checking for source changes:
  this bot intentionally triggers a fresh workflow every hour.
Four-file project
This project contains only:
- bot.py
- .env
- requirements.txt
- README.md