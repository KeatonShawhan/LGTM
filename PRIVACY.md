# Privacy Policy

**Last updated: March 2026**

## Overview

LGTM is an AI-powered code review GitHub App. This policy describes what data LGTM accesses and how it is handled.

## Data Accessed

When installed, LGTM requests the following GitHub permissions:

- **Pull requests**: Read access to pull request metadata and diffs
- **Repository contents**: Read access to clone code for review
- **Pull request reviews**: Write access to post review comments

## How Data Is Used

When a pull request is opened or updated in a repository where LGTM is installed:

1. The pull request's code diff is cloned to a temporary directory on the server
2. The diff is sent to the **Anthropic Claude API** for AI-powered analysis
3. Review findings are posted back to the pull request as comments
4. The cloned code is **immediately and permanently deleted** after the review completes

## Data Storage

LGTM does **not** persistently store:
- Source code or diffs
- Pull request content
- User data or identifiers

No database is used. Each review is stateless and self-contained.

## Third-Party Services

LGTM uses the **Anthropic Claude API** to perform code analysis. Code diffs are transmitted to Anthropic's API during review. Anthropic's privacy policy is available at [anthropic.com/privacy](https://www.anthropic.com/privacy).

## Data Retention

No user data is retained beyond the duration of a single review request (typically under 2 minutes).

## Contact

For privacy questions or concerns, open an issue at [github.com/KeatonShawhan/LGTM](https://github.com/KeatonShawhan/LGTM).
