"""Server configuration — loaded from environment variables."""
import base64
import os
from dotenv import load_dotenv

load_dotenv()

# GitHub App credentials
GITHUB_APP_ID: str = os.environ["GITHUB_APP_ID"]

# Private key: accept either base64-encoded (preferred for env vars) or raw PEM
_raw_key = os.environ["GITHUB_APP_PRIVATE_KEY"]
if "BEGIN" not in _raw_key:
    # base64-encoded — decode it
    GITHUB_APP_PRIVATE_KEY: str = base64.b64decode(_raw_key).decode("utf-8")
else:
    # Raw PEM — normalize any literal \n escapes
    GITHUB_APP_PRIVATE_KEY: str = _raw_key.replace("\\n", "\n")
GITHUB_WEBHOOK_SECRET: str = os.environ["GITHUB_WEBHOOK_SECRET"]

# Anthropic
ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]

# Optional: model override (defaults to sonnet)
REVIEW_MODEL: str = os.environ.get("REVIEW_MODEL", "claude-sonnet-4-6")
