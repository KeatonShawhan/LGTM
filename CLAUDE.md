### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately - don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update 'tasks/lessons.md' with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests -> then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management
1. **Plan First**: Write plan to 'tasks/todo.md' with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review to 'tasks/todo.md'
6. **Capture Lessons**: Update 'tasks/lessons.md' after corrections

## Core Principles
- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.


## LGTM Architecture Overview

LGTM is an agentic code review system. The pipeline flows through five stages:

### 1. Repository Ingestion
- User-provided Git refs (branch, tag, range, SHA) are normalized to immutable commit SHAs
- Repositories are cached by `(repo_id, commit_sha)`
- Only commit SHAs are persisted; symbolic refs are resolved transiently

### 2. ChangeSet Computation
- Computes diffs between `(base_commit, head_commit)`
- Produces immutable, cacheable `ChangeSet` artifacts
- Includes per-file hunks and diff metadata for downstream risk scoring and context selection

### 3. Librarian / Code Context Builder
- **Role**: Deterministic context curation — selects information, never interprets it
- Builds a layered `CodeContext` with progressive depth:
  - Diff metadata → File summaries → Symbols (functions, classes, imports) → Targeted code snippets
- Context depth governed by: deterministic heuristics, policy gates, budget constraints, risk scoring
- LLMs may *recommend* deeper context, but all descent decisions are enforced by workflow logic
- Output: read-only, structured `CodeContext` — the sole knowledge source for downstream agents

### 4. Agentic Review Generation
- Long-running, tool-using agent orchestrated by **Temporal** (executed inside activities)
- The review agent:
  - Operates over the provided `CodeContext`
  - Maintains internal state across reasoning steps
  - Iteratively refines hypotheses and findings
- Available tools (scoped, auditable, mediated by activity-level contracts):
  - Static analysis helpers
  - Rule-based validators
  - Summarization / comparison utilities
- **Key constraint**: Agent does not control workflow execution, fetch arbitrary context, or escalate depth on its own — all authority remains with deterministic workflows

### 5. Review Artifacts & Validation
- Agent produces structured findings: explicit claims, grounded evidence (symbols/snippets), suggestions, confidence scores
- System-level validators enforce: evidence grounding, output schema correctness, policy compliance
- Workflow deterministically decides whether:
  - Review is complete
  - More context would help (without auto-escalation)
  - Findings should be surfaced, filtered, or rejected

### Observability
- Lightweight post-review tracing via LangChain to inspect agent reasoning and tool usage
- Does not impact workflow determinism or execution