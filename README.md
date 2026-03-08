# LGTM

An agentic code review system built on the Claude Agent SDK. Install it as a **GitHub App** to get automatic AI-powered PR reviews, or run it locally via CLI.

LGTM ingests a Git repository and ref, constructs a layered code context, and runs an iterative review agent that produces structured findings with grounded evidence — validated deterministically before surfacing.

---

## GitHub App

Install LGTM on your repository to get automatic code reviews on every pull request — no configuration needed.

**How it works:**
1. Open a pull request
2. LGTM clones the PR branch, runs the full agentic review pipeline
3. Findings are posted as a PR review with severity-grouped findings, evidence snippets, and fix suggestions

**Self-hosting:**

Deploy your own instance in minutes:

```bash
# 1. Clone and install
git clone https://github.com/KeatonShawhan/LGTM.git
cd LGTM
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Fill in GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY, GITHUB_WEBHOOK_SECRET, ANTHROPIC_API_KEY

# 3. Run the webhook server
uvicorn server.app:app --host 0.0.0.0 --port 3000
```

**Deploy to Railway (one command):**

```bash
railway up
```

**Required environment variables for the server:**

| Variable | Description |
|----------|-------------|
| `GITHUB_APP_ID` | GitHub App ID (numeric) |
| `GITHUB_APP_PRIVATE_KEY` | RSA private key from GitHub App settings (PEM) |
| `GITHUB_WEBHOOK_SECRET` | Webhook secret configured in GitHub App settings |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `REVIEW_MODEL` | Optional model override (default: `claude-sonnet-4-6`) |

**GitHub App setup (one-time):**
1. Go to GitHub → Settings → Developer settings → GitHub Apps → New GitHub App
2. Set the webhook URL to `https://your-server.com/webhook`
3. Subscribe to `Pull requests` events
4. Generate a private key and copy the App ID
5. Install the app on your repo

---

## Architecture

LGTM processes pull requests through a five-stage pipeline orchestrated by [Temporal](https://temporal.io/):

```
Repository Ingestion → ChangeSet Computation → Code Context → Agentic Review → Evidence Validation
```

1. **Repository Ingestion** — Resolves symbolic refs (branch/tag) to immutable commit SHAs and caches clones by `(repo_id, commit_sha)`.
2. **ChangeSet Computation** — Diffs `base_commit..head_commit` into a structured, cacheable `ChangeSet` with per-file hunks.
3. **Code Context Builder** — Deterministically curates a layered `CodeContext` (diff metadata → file summaries → risk scores) without LLM interpretation.
4. **Agentic Review** — A tool-using Claude agent iterates over the `CodeContext`, reads code on demand, delegates sub-tasks to subagents, and manages a 40% token budget. The agent terminates via a `submit_review` tool call or budget exhaustion.
5. **Evidence Validation** — Findings are validated deterministically (zero LLM calls): file existence, line-number validity, symbol grounding, and code-fragment matching. Confidence scores are adjusted up or down based on evidence quality.

---

## Features

- **Multi-turn agentic review** with tool use, subagent delegation, and automatic context summarization
- **Risk-scored file prioritization** — focuses review effort on high-churn, high-risk files
- **Deterministic evidence validation** — rejects hallucinated findings before they surface
- **Token budget management** — enforces a configurable fraction of the model's context window
- **LRU + TTL caching** for cloned repos and file summaries
- **LangSmith observability** — trace logs for agent reasoning and tool usage (optional)
- **Benchmark framework** — 17 labeled test cases across Python, JavaScript/TypeScript, and Go with a two-tier scorer (deterministic + LLM-as-judge)

---

## Requirements

- Python 3.13+
- [Temporal](https://docs.temporal.io/cli) server running locally (for the full workflow pipeline)
- An [Anthropic API key](https://console.anthropic.com/)

---

## Setup

```bash
git clone https://github.com/KeatonShawhan/LGTM.git
cd LGTM
pip install -r requirements.txt

cp .env.example .env
# Edit .env and fill in your ANTHROPIC_API_KEY
```

---

## Usage

### Run a code review

Start a local Temporal server, then:

```bash
python main.py review \
  --repo https://github.com/owner/repo \
  --ref main \
  [--use-cache]
```

| Flag | Description |
|------|-------------|
| `--repo` | Repository URL |
| `--ref` | Branch name, tag, or commit SHA to review |
| `--use-cache` | Reuse cached file summaries from previous runs |

---

## Benchmark Suite

The benchmark framework evaluates review quality without Temporal — it calls the pipeline functions directly for fast iteration.

### Run all cases

```bash
python -m benchmarks.runner
```

### Options

```bash
python -m benchmarks.runner --case null_deref_001   # single case
python -m benchmarks.runner --model haiku            # cheaper model
python -m benchmarks.runner --concurrency 5          # parallel workers
```

| Flag | Default | Description |
|------|---------|-------------|
| `--case` | all | Run a specific case by ID |
| `--model` | `sonnet` | `haiku`, `sonnet`, or `opus` |
| `--concurrency` | `3` | Number of cases to run in parallel |

### Suite composition (v2)

| Language | Bug Cases | Clean Cases | Total |
|----------|-----------|-------------|-------|
| Python | 8 | 1 | 9 |
| JavaScript / TypeScript | 3 | 1 | 4 |
| Go | 4 | 0 | 4 |
| **Total** | **15** | **2** | **17** |

Bug categories: 9 logic bugs, 4 security, 2 performance.

### Scoring

Each case is scored with a **two-tier system**:

- **Tier 1 (deterministic):** Weighted rubric across file path, line location, category, severity, and keyword overlap. Match threshold ≥ 0.50.
- **Tier 2 (LLM-as-judge):** Claude Haiku evaluates unmatched expected findings against same-file actual findings.

Metrics reported per case and in aggregate: **Precision**, **Recall**, **F1**, clean-region violations, token usage, and wall time.

See [`benchmarks/RUBRIC.md`](benchmarks/RUBRIC.md) for full scoring details.

---

## Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `GITHUB_TOKEN` | No | GitHub PAT — required for private repos |
| `LANGSMITH_API_KEY` | No | Enables LangSmith tracing |

---

## Project Structure

```
activities/         Temporal activities (clone, diff, review, validate, cache, ...)
agents/             Claude agent factory and base configuration
benchmarks/         Benchmark runner, scorer, grader, and 17 labeled test cases
cache/              LRU+TTL caching for repos and file summaries
config/             Agent model and prompt configuration
observability/      LangChain tracing integration
utils/              Shared dataclasses
workflows/          Temporal workflow definitions
main.py             CLI entry point
```
