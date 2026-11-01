# Slipstream Link Generator

An authenticated web app that builds the Slipstream site once, then deploys the same build to Surge, Vercel, and Cloudflare Pages in parallel.

## What it does
- Shallow-clones [slipstream-fr](https://github.com/akilesh-boddu/slipstream-fr).
- Runs `npm ci`, `npm test`, and `npm run build` once.
- Deploys the resulting `dist/` to three providers concurrently.
- Applies timeouts and shows each provider's result independently.
- Keeps local deployment history in `.deployments/`.

## Configure
Copy `.env.example` to `.env` and fill in your credentials. Never commit `.env` or share tokens.

Required:
- `ADMIN_PASSWORD`
- `SURGE_TOKEN`
- `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`
- `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`

Optional: `CLOUDFLARE_PROJECT`, `PUBLIC_API_URL`, `WISP_URL`, `BUILD_TIMEOUT_SECONDS`, `DEPLOY_TIMEOUT_SECONDS`, `PORT`.

## Run in Codespaces
Requires Python 3.10+, Git, Node.js 22+, and npm.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your private credentials, then:
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open port 8000, enter the admin password, and click **Make URLs**.

Windows PowerShell activation: `.venv\\Scripts\\Activate.ps1`.

## Provider details
- Surge gets a new `slip-...` subdomain each run.
- Vercel creates a unique preview deployment in the configured existing project.
- Cloudflare Pages uses a unique preview branch in the configured Pages project (created if missing).
- Provider quotas and account permissions still apply; URLs are only shown for successful deployments.
- Codespaces is for testing, not permanent public hosting. A public generator needs an always-on host with the same environment variables and authentication.
- Slipstream AI/Wisp features still depend on the separate backend configured by `PUBLIC_API_URL` and `WISP_URL`.
