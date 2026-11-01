import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("link-gen")

ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / ".deployments"
HISTORY.mkdir(exist_ok=True)
REPO_URL = os.getenv("SOURCE_REPO", "https://github.com/akilesh-boddu/slipstream-fr.git")
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "https://base-of-work.onrender.com")
WISP_URL = os.getenv("WISP_URL", "wss://base-of-work.onrender.com/wisp/")
BUILD_TIMEOUT = int(os.getenv("BUILD_TIMEOUT_SECONDS", "900"))
DEPLOY_TIMEOUT = int(os.getenv("DEPLOY_TIMEOUT_SECONDS", "300"))
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
lock = threading.Lock()
security = HTTPBasic()
app = FastAPI(title="Slipstream Link Generator")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

def auth(credentials: HTTPBasicCredentials = Depends(security)):
    if not ADMIN_PASSWORD or not secrets.compare_digest(credentials.password, ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="Invalid admin password", headers={"WWW-Authenticate": "Basic"})
    return True

def run(command, cwd, timeout, env=None):
    log.info("Running: %s", " ".join(command[:3]) + (" ..." if len(command) > 3 else ""))
    result = subprocess.run(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError((result.stdout or "Command failed")[-3500:])
    return result.stdout or ""

def slug():
    return "slip-" + datetime.now(timezone.utc).strftime("%y%m%d-%H%M%S") + "-" + secrets.token_hex(2)

def provider_env():
    env = os.environ.copy()
    env.update({"PUBLIC_API_URL": PUBLIC_API_URL, "WISP_URL": WISP_URL, "CI": "1"})
    return env

def deploy_surge(dist, name, env):
    token = env.get("SURGE_TOKEN", "")
    if not token:
        raise RuntimeError("SURGE_TOKEN is missing")
    output = run(["npx", "--yes", "surge", str(dist), name + ".surge.sh", "--token", token],
                 dist.parent, DEPLOY_TIMEOUT, env)
    return {"provider": "Surge", "url": "https://" + name + ".surge.sh", "log": output[-800:]}

def deploy_vercel(dist, name, env):
    token = env.get("VERCEL_TOKEN", "")
    project = env.get("VERCEL_PROJECT_ID", "")
    scope = env.get("VERCEL_ORG_ID", "")
    if not token or not project or not scope:
        raise RuntimeError("VERCEL_TOKEN, VERCEL_PROJECT_ID and VERCEL_ORG_ID are required")
    work = dist.parent
    run(["npx", "--yes", "vercel", "link", "--yes", "--project", project, "--scope", scope, "--token", token],
        work, DEPLOY_TIMEOUT, env)
    run(["npx", "--yes", "vercel", "build", "--token", token], work, DEPLOY_TIMEOUT, env)
    output = run(["npx", "--yes", "vercel", "deploy", "--prebuilt", "--yes", "--token", token],
                 work, DEPLOY_TIMEOUT, env)
    urls = re.findall(r"https://[A-Za-z0-9._-]+\\.vercel\\.app", output)
    if not urls:
        raise RuntimeError("Vercel completed but did not return a deployment URL. Output: " + output[-1200:])
    return {"provider": "Vercel", "url": urls[-1], "log": output[-800:]}

def deploy_cloudflare(dist, name, env):
    token = env.get("CLOUDFLARE_API_TOKEN", "")
    account = env.get("CLOUDFLARE_ACCOUNT_ID", "")
    project = env.get("CLOUDFLARE_PROJECT", "slipstream-generator")
    if not token or not account:
        raise RuntimeError("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID are required")
    check = subprocess.run(["npx", "--yes", "wrangler", "pages", "project", "list"],
                           cwd=dist.parent, env=env, text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=90)
    if project not in check.stdout:
        run(["npx", "--yes", "wrangler", "pages", "project", "create", project, "--production-branch", "main"],
            dist.parent, 120, env)
    output = run(["npx", "--yes", "wrangler", "pages", "deploy", str(dist),
                  "--project-name", project, "--branch", name], dist.parent, DEPLOY_TIMEOUT, env)
    urls = re.findall(r"https://[A-Za-z0-9._-]+\\.pages\\.dev", output)
    url = urls[-1] if urls else "https://" + name + "." + project + ".pages.dev"
    return {"provider": "Cloudflare Pages", "url": url, "log": output[-800:]}

def deploy_all():
    if not lock.acquire(blocking=False):
        raise RuntimeError("A deployment is already running. Wait for it to finish.")
    started = datetime.now(timezone.utc).isoformat()
    record = {"id": slug(), "started": started, "status": "building", "results": []}
    try:
        with tempfile.TemporaryDirectory(prefix="slipstream-linkgen-") as temp:
            work = Path(temp) / "source"
            env = provider_env()
            run(["git", "clone", "--depth", "1", REPO_URL, str(work)], Path(temp), 180, env)
            run(["npm", "ci", "--no-audit", "--no-fund"], work, BUILD_TIMEOUT, env)
            run(["npm", "test"], work, BUILD_TIMEOUT, env)
            run(["npm", "run", "build"], work, BUILD_TIMEOUT, env)
            dist = work / "dist"
            if not dist.is_dir() or not any(dist.iterdir()):
                raise RuntimeError("Build finished but dist/ is missing or empty")
            record["status"] = "deploying"
            jobs = {
                "Surge": lambda: deploy_surge(dist, record["id"], env),
                "Vercel": lambda: deploy_vercel(dist, record["id"], env),
                "Cloudflare Pages": lambda: deploy_cloudflare(dist, record["id"], env),
            }
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = {pool.submit(fn): provider for provider, fn in jobs.items()}
                for future in as_completed(futures):
                    provider = futures[future]
                    try:
                        result = future.result()
                        record["results"].append(result)
                    except Exception as exc:
                        log.exception("%s deployment failed", provider)
                        record["results"].append({"provider": provider, "error": str(exc)[-2500:]})
        record["status"] = "complete" if any("url" in r for r in record["results"]) else "failed"
    except subprocess.TimeoutExpired as exc:
        record["status"] = "failed"
        record["error"] = f"Timed out after {exc.timeout} seconds while running: {exc.cmd}"
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = str(exc)[-3500:]
        log.exception("Build/deployment failed")
    finally:
        record["finished"] = datetime.now(timezone.utc).isoformat()
        path = HISTORY / (record["id"] + ".json")
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        lock.release()
    return record

@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")

@app.get("/api/health")
def health():
    return {"ok": True, "configured": bool(ADMIN_PASSWORD)}

@app.post("/api/deploy")
def create_deployment(_: bool = Depends(auth)):
    return deploy_all()

@app.get("/api/history")
def history(_: bool = Depends(auth)):
    records = []
    for path in sorted(HISTORY.glob("*.json"), reverse=True)[:20]:
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return records

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
