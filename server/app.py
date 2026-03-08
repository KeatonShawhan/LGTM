"""
LGTM GitHub App — webhook server.

Receives GitHub pull_request events, runs the agentic review pipeline,
and posts findings back as a PR review.

Run locally:
    uvicorn server.app:app --reload --port 3000

Environment variables required:
    GITHUB_APP_ID          GitHub App ID (numeric)
    GITHUB_APP_PRIVATE_KEY RSA private key (PEM format, with \\n escapes OK)
    GITHUB_WEBHOOK_SECRET  Webhook secret configured in GitHub App settings
    ANTHROPIC_API_KEY      Anthropic API key
    REVIEW_MODEL           Optional model override (default: claude-sonnet-4-6)
"""
import hashlib
import hmac
import logging

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse

from server import config
from server.github_client import (
    get_installation_token,
    post_pr_review,
    post_status_comment,
)
from server.pipeline import run_pr_review

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="LGTM", description="Agentic code review GitHub App")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Webhook signature validation
# ---------------------------------------------------------------------------

def _verify_signature(body: bytes, signature_header: str | None) -> bool:
    """Validate the GitHub webhook HMAC-SHA256 signature."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        config.GITHUB_WEBHOOK_SECRET.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature_header)


# ---------------------------------------------------------------------------
# Background review task
# ---------------------------------------------------------------------------

async def _handle_pull_request(
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    head_ref: str,
    base_sha: str,
    clone_url: str,
    installation_id: int,
) -> None:
    """Run the full review pipeline and post results. Executed in the background."""
    log.info("Starting review: %s/%s#%d head=%s", owner, repo, pr_number, head_sha[:8])
    try:
        token = await get_installation_token(
            installation_id,
            config.GITHUB_APP_ID,
            config.GITHUB_APP_PRIVATE_KEY,
        )

        result = await run_pr_review(
            owner=owner,
            repo=repo,
            head_sha=head_sha,
            head_ref=head_ref,
            base_sha=base_sha,
            clone_url=clone_url,
            installation_token=token,
            model=config.REVIEW_MODEL,
        )

        # Refresh token before posting (review can take minutes)
        token = await get_installation_token(
            installation_id,
            config.GITHUB_APP_ID,
            config.GITHUB_APP_PRIVATE_KEY,
        )
        await post_pr_review(owner, repo, pr_number, token, result)
        log.info(
            "Review posted: %s/%s#%d — %d finding(s)",
            owner, repo, pr_number, len(result.findings),
        )

    except Exception:
        log.exception("Review failed for %s/%s#%d", owner, repo, pr_number)
        try:
            # Best-effort error comment so the PR author knows something went wrong
            token = await get_installation_token(
                installation_id,
                config.GITHUB_APP_ID,
                config.GITHUB_APP_PRIVATE_KEY,
            )
            await post_status_comment(
                owner, repo, pr_number, token,
                "⚠️ **LGTM** encountered an error while reviewing this PR. "
                "Please check the server logs or try re-triggering by pushing a new commit.",
            )
        except Exception:
            log.exception("Failed to post error comment for %s/%s#%d", owner, repo, pr_number)


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------

@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()

    if not _verify_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event = request.headers.get("X-GitHub-Event", "")

    # Only handle pull_request events
    if event != "pull_request":
        return JSONResponse({"status": "ignored", "event": event})

    payload = await request.json()
    action = payload.get("action", "")

    # Only trigger on open / update / reopen
    if action not in ("opened", "synchronize", "reopened"):
        return JSONResponse({"status": "ignored", "action": action})

    pr = payload["pull_request"]
    repo_data = payload["repository"]
    installation_id: int = payload["installation"]["id"]

    owner: str = repo_data["owner"]["login"]
    repo: str = repo_data["name"]
    pr_number: int = pr["number"]
    head_sha: str = pr["head"]["sha"]
    head_ref: str = pr["head"]["ref"]           # branch name
    base_sha: str = pr["base"]["sha"]
    # Use the head repo's clone URL so fork PRs work correctly
    clone_url: str = pr["head"]["repo"]["clone_url"]

    log.info(
        "Queuing review: %s/%s#%d action=%s head=%s",
        owner, repo, pr_number, action, head_sha[:8],
    )

    background_tasks.add_task(
        _handle_pull_request,
        owner, repo, pr_number, head_sha, head_ref, base_sha, clone_url, installation_id,
    )

    return JSONResponse({"status": "queued", "pr": pr_number})
