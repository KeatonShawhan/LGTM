"""
GitHub App client — authentication, repo cloning, and PR review posting.

Flow:
  1. generate_app_jwt()          → short-lived JWT signed with App private key
  2. get_installation_token()    → scoped access token for a specific installation
  3. clone_repo_with_token()     → authenticated git clone
  4. post_pr_review()            → posts findings as a GitHub PR review
"""
import time
import subprocess
import tempfile
from pathlib import Path

import httpx
import jwt  # PyJWT

from utils.dataclasses import ReviewResult, ReviewFinding, ChangeSet


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def generate_app_jwt(app_id: str, private_key: str) -> str:
    """Generate a short-lived JWT to authenticate as the GitHub App."""
    now = int(time.time())
    payload = {
        "iat": now - 60,   # issued 60s ago to allow for clock drift
        "exp": now + 600,  # valid for 10 minutes
        "iss": app_id,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


async def get_installation_token(installation_id: int, app_id: str, private_key: str) -> str:
    """Exchange App JWT for an installation-scoped access token."""
    app_jwt = generate_app_jwt(app_id, private_key)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        resp.raise_for_status()
        return resp.json()["token"]


# ---------------------------------------------------------------------------
# Repository cloning
# ---------------------------------------------------------------------------

def clone_repo_with_token(clone_url: str, token: str, dest: Path, branch: str | None = None) -> None:
    """Clone a GitHub repo into dest using an installation access token."""
    auth_url = clone_url.replace("https://", f"https://x-access-token:{token}@")
    # --no-single-branch fetches all branches so base_sha (e.g. main) is available for diffing
    cmd = ["git", "clone", "--depth", "50", "--no-single-branch"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [auth_url, str(dest)]
    subprocess.run(cmd, check=True, capture_output=True)


# ---------------------------------------------------------------------------
# PR review posting
# ---------------------------------------------------------------------------

SEVERITY_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🔵",
}

CATEGORY_LABEL = {
    "bug": "Bug",
    "security": "Security",
    "performance": "Performance",
    "style": "Style",
}


def _diff_line_set(change_set: ChangeSet) -> dict[str, set[int]]:
    """
    Return {file_path: set of new-file line numbers that appear in the diff}.

    Only lines present in a hunk (added '+' or context ' ') are valid targets
    for GitHub inline review comments.  Deleted lines ('-') exist only in the
    old file and are not addressable on the RIGHT side.
    """
    result: dict[str, set[int]] = {}
    for cf in change_set.files:
        lines: set[int] = set()
        for hunk in cf.hunks:
            line_no = hunk.start
            for diff_line in hunk.lines:
                if diff_line.startswith('-'):
                    pass  # removed line — not in new file
                else:
                    lines.add(line_no)
                    line_no += 1
        if lines:
            result[cf.path] = lines
    return result


def _format_inline_comment(f: ReviewFinding) -> str:
    """Format a single finding as a concise inline comment body."""
    conf = f.confidence_adjusted if f.confidence_adjusted is not None else f.confidence
    cat = CATEGORY_LABEL.get(f.category, f.category.title())
    parts = [
        f"{SEVERITY_EMOJI.get(f.severity, '')} **{f.title}**",
        f"*{f.severity.capitalize()} · {cat} · {conf:.0%} confidence*",
        "",
    ]
    if f.evidence:
        parts.append(f"> {f.evidence.strip()}")
        parts.append("")
    if f.suggestion:
        parts.append(f"💡 **Suggestion:** {f.suggestion}")
    return "\n".join(parts)


def _format_review_body(result: ReviewResult, overflow_findings: list[ReviewFinding] | None = None) -> str:
    """
    Render a ReviewResult as a GitHub Markdown PR review body.

    overflow_findings: findings that could not be placed as inline comments
    (their line numbers are not in the diff).  When None, all findings are
    rendered in the body (backwards-compatible fallback).
    """
    overflow = overflow_findings if overflow_findings is not None else result.findings
    inline_count = len(result.findings) - len(overflow)

    lines = ["## LGTM Code Review\n"]
    lines.append(f"**{result.summary}**\n")

    if result.warnings:
        lines.append("### ⚠️ Warnings")
        for w in result.warnings:
            lines.append(f"- {w}")
        lines.append("")

    total = len(result.findings)
    if total == 0:
        lines.append("No issues found. Looks good! ✅")
    else:
        stats = result.stats or {}
        badge_parts = []
        for sev in ("critical", "high", "medium", "low"):
            count = stats.get(sev, 0)
            if count:
                badge_parts.append(f"{SEVERITY_EMOJI.get(sev, '')} {sev.capitalize()}: **{count}**")
        if badge_parts:
            lines.append("  ".join(badge_parts) + "\n")

        if inline_count > 0:
            noun = "comment" if inline_count == 1 else "comments"
            lines.append(f"*{inline_count} inline {noun} posted on the affected lines.*\n")

        if overflow:
            lines.append(f"### Additional Findings ({len(overflow)})\n")
            order = ["critical", "high", "medium", "low"]
            by_severity: dict[str, list[ReviewFinding]] = {s: [] for s in order}
            for f in overflow:
                bucket = f.severity if f.severity in by_severity else "low"
                by_severity[bucket].append(f)
            for sev in order:
                bucket_findings = by_severity[sev]
                if not bucket_findings:
                    continue
                emoji = SEVERITY_EMOJI.get(sev, "")
                lines.append(f"#### {emoji} {sev.capitalize()} ({len(bucket_findings)})\n")
                for f in bucket_findings:
                    conf = f.confidence_adjusted if f.confidence_adjusted is not None else f.confidence
                    cat = CATEGORY_LABEL.get(f.category, f.category.title())
                    lines.append(f"---\n**`{f.file_path}:{f.line_number}`** — {f.title}")
                    lines.append(f"*{SEVERITY_EMOJI.get(f.severity, '')} {f.severity.capitalize()} · {cat} · {conf:.0%} confidence*\n")
                    if f.evidence:
                        lines.append(f"> {f.evidence.strip()}\n")
                    if f.suggestion:
                        lines.append(f"💡 **Suggestion:** {f.suggestion}")
                    lines.append("")

    conf_pct = result.overall_confidence * 100
    lines.append(f"---\n*Overall confidence: {conf_pct:.0f}% · Powered by [LGTM](https://github.com/KeatonShawhan/LGTM)*")
    return "\n".join(lines)


async def post_pr_review(
    owner: str,
    repo: str,
    pr_number: int,
    token: str,
    result: ReviewResult,
    head_sha: str = "",
    change_set: ChangeSet | None = None,
) -> None:
    """
    Post a PR review.

    When head_sha and change_set are provided, findings whose line numbers fall
    inside a diff hunk are posted as inline comments on the exact line.
    Findings outside the diff are included in the review body instead.
    """
    # Partition findings: inline (line is in the diff) vs overflow (body only)
    inline_comments: list[dict] = []
    overflow: list[ReviewFinding] = []

    if change_set is not None and head_sha:
        valid_lines = _diff_line_set(change_set)
        for f in result.findings:
            if (
                f.line_number
                and f.file_path in valid_lines
                and f.line_number in valid_lines[f.file_path]
            ):
                inline_comments.append({
                    "path": f.file_path,
                    "line": f.line_number,
                    "side": "RIGHT",
                    "body": _format_inline_comment(f),
                })
            else:
                overflow.append(f)
    else:
        overflow = list(result.findings)

    body = _format_review_body(result, overflow_findings=overflow)

    # Use COMMENT (not REQUEST_CHANGES / APPROVE) so the bot doesn't gate merges
    payload: dict = {"body": body, "event": "COMMENT"}
    if head_sha:
        payload["commit_id"] = head_sha
    if inline_comments:
        payload["comments"] = inline_comments

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json=payload,
        )
        resp.raise_for_status()


async def post_status_comment(
    owner: str,
    repo: str,
    pr_number: int,
    token: str,
    message: str,
) -> None:
    """Post a plain issue comment on a PR (used for status/error messages)."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"body": message},
        )
        resp.raise_for_status()
