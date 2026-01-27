# LGTM - Automated PR Code Review

## Overview

LGTM is a CLI tool that automates GitHub pull request code reviews using Temporal workflows and Claude AI. It clones repositories, analyzes git diffs, prioritizes files by risk, generates AI summaries, and builds structured code context for intelligent review.

## Tech Stack

- **Language**: Python 3
- **Workflow Orchestration**: Temporal (workflows + activities)
- **AI**: Anthropic Claude API (haiku for summaries)
- **Agent Framework**: Claude Agent SDK
- **Configuration**: dotenv for environment variables

## Project Structure

```
LGTM/
├── main.py                 # CLI entry point, Temporal worker setup
├── workflows/              # Temporal workflow definitions
│   ├── review.py           # Parent workflow orchestrating the review
│   ├── ingestRepositoryWorkflow.py
│   ├── computeChangeSetWorkflow.py
│   └── buildCodeContextWorkflow.py
├── activities/             # Atomic Temporal activities
│   ├── resolveCloneable.py # URL normalization, reference resolution
│   ├── cloneRepo.py        # Git clone operations
│   ├── matchCommit.py      # Checkout specific commits
│   ├── cacheRepo.py        # Repository cache operations
│   ├── gitDiff.py          # Diff parsing and computation
│   ├── prioritizeFiles.py  # Risk-based file scoring
│   └── summarizeFile.py    # AI-powered file summarization
├── agents/                 # Claude-based AI agents
│   ├── base.py             # AgentFactory for creating agents
│   └── query.py            # QueryAgent for simple queries
├── cache/                  # Caching implementations
│   ├── repo_cache.py       # LRU+TTL cache for cloned repos
│   └── file_summary_cache.py # LRU+TTL cache for file summaries
├── config/                 # Agent configurations
│   ├── calcAgentConfig.py
│   └── codeAnalysisAgentConfig.py
├── utils/
│   └── dataclasses.py      # Domain model dataclasses
└── mcpSetup/               # MCP server setup
```

## Essential Commands

### Prerequisites
- Temporal server running locally on port 7233
- `ANTHROPIC_API_KEY` environment variable set

### Run a Review
```bash
python main.py review --repo <github-url> --ref <branch|tag|commit>
```

Options:
- `--repo`: GitHub repository URL (required)
- `--ref`: Git reference - branch, tag, or commit SHA (required)
- `--use-cache`: Use cached file summaries when available

### Examples
```bash
# Review a specific branch
python main.py review --repo https://github.com/user/repo --ref feature-branch

# Review a specific commit
python main.py review --repo user/repo --ref abc123

# Review with cached summaries
python main.py review --repo user/repo --ref main --use-cache
```

## Key Domain Concepts

- **RepoHandle**: Repository identity (repo_id, repo_path, commit_sha) - `utils/dataclasses.py:23`
- **ChangeSet**: Git diff representation (base_commit, head_commit, files) - `utils/dataclasses.py:17`
- **CodeContext**: Layered context with overview and file details - `utils/dataclasses.py:90`
- **PrioritizedFile**: File with risk score and prioritization - `utils/dataclasses.py:29`

## Review Pipeline Flow

1. **IngestRepository** - Resolve URL, check cache, clone repo, checkout commit
2. **ComputeChangeSet** - Parse git diff between HEAD and main branch
3. **BuildCodeContext** - Prioritize files by risk, generate AI summaries

## Additional Documentation

For detailed architectural patterns and conventions, see:
- `.claude/docs/architectural_patterns.md` - Temporal patterns, caching, domain model design
