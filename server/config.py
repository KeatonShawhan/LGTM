"""Server configuration — loaded from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

# GitHub App credentials
GITHUB_APP_ID: str = os.environ["GITHUB_APP_ID"]
# Private key may be stored with literal \n escapes in env vars
GITHUB_APP_PRIVATE_KEY: str = os.environ["GITHUB_APP_PRIVATE_KEY"].replace("\\n", "\n")
GITHUB_WEBHOOK_SECRET: str = os.environ["GITHUB_WEBHOOK_SECRET"]

# Anthropic
ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]

# Optional: model override (defaults to sonnet)
REVIEW_MODEL: str = os.environ.get("REVIEW_MODEL", "claude-sonnet-4-6")
