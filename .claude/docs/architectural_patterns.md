# Architectural Patterns

## Temporal Workflow Patterns

### Parent-Child Workflow Orchestration
The review process uses a parent workflow that orchestrates child workflows in sequence. Each child workflow handles a distinct phase.

**Pattern**: Parent workflow calls `workflow.execute_child_workflow()` with retry policies.

**Example** (`workflows/review.py:30-36`):
```python
repo_handle = await workflow.execute_child_workflow(
    IngestRepositoryWorkflow.run,
    args=[repo, ref],
    id=f"clone-{workflow.info().workflow_id}",
    task_queue="code-dev-queue",
    retry_policy=RetryPolicy(maximum_attempts=2),
)
```

**Applied in**:
- `workflows/review.py` - Parent orchestrator
- `workflows/ingestRepositoryWorkflow.py` - Repository ingestion
- `workflows/computeChangeSetWorkflow.py` - Diff computation
- `workflows/buildCodeContextWorkflow.py` - Context building

### Activity Pattern with Heartbeats
Activities are atomic, retriable operations. Long-running activities use heartbeats to report progress and prevent timeouts.

**Pattern**: Decorate with `@activity.defn`, call `activity.heartbeat()` for progress.

**Example** (`activities/cloneRepo.py:137`):
```python
activity.heartbeat(f"Cloning {normalized_url} to {clone_path}")
```

**Applied in**: All files in `activities/` directory

### Temporal Serialization Handling
Temporal serializes dataclasses to dicts when passing between workflows/activities. Code handles both formats.

**Pattern**: Check `isinstance(data, dict)` and handle both dict and object access.

**Example** (`activities/prioritizeFiles.py:169-178`):
```python
if isinstance(file_data, dict):
    file_path = file_data.get('path', '')
else:
    file_path = file_data.path
```

**Applied in**:
- `activities/prioritizeFiles.py:159-178`
- `workflows/buildCodeContextWorkflow.py:136-140`

---

## Caching Patterns

### LRU+TTL Cache with Disk Persistence
Caches combine LRU eviction (size limit) and TTL eviction (time limit) with JSON persistence.

**Pattern**: `OrderedDict` for LRU ordering, timestamp tracking for TTL, atomic file writes.

**Key components**:
- `_evict_expired()` - Remove entries past TTL
- `_evict_lru()` - Remove oldest when at capacity
- `_save_to_disk()` / `_load_from_disk()` - JSON persistence

**Applied in**:
- `cache/repo_cache.py:13-244` - Repository clone cache
- `cache/file_summary_cache.py:13-350` - File summary cache

### Global Singleton Cache Access
Caches use module-level singleton pattern with lazy initialization.

**Pattern**: Private module variable + getter function.

**Example** (`cache/repo_cache.py:247-284`):
```python
_cache_instance: Optional[LRUTTLCache] = None

def get_cache(...) -> LRUTTLCache:
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = LRUTTLCache(...)
    return _cache_instance
```

**Applied in**:
- `cache/repo_cache.py:247-284`
- `cache/file_summary_cache.py:353-390`

### Composite Cache Keys
Caches use tuples as keys to uniquely identify cached items.

**Repo cache key**: `(repo_id, commit_sha)` - `cache/repo_cache.py:47`
**Summary cache key**: `(repo_id, commit_sha, file_path, summarizer_version)` - `cache/file_summary_cache.py:47`

---

## Domain Model Patterns

### Frozen Dataclasses for Immutability
Domain objects use `@dataclass(frozen=True)` to ensure immutability.

**Pattern**: Frozen dataclasses cannot be modified after creation; create new instances instead.

**Example** (`utils/dataclasses.py:29-34`):
```python
@dataclass(frozen=True)
class PrioritizedFile:
    path: str
    risk_score: float
    priority: int
    reasons: list[str]
```

**Applied in**: All dataclasses in `utils/dataclasses.py` except mutable ones (Hunk, ChangedFile, ChangeSet)

### Layered Context Model
Code context is organized in layers: Layer 0 (overview) provides high-level stats, Layer 1+ provides per-file details.

**Structure** (`utils/dataclasses.py:90-101`):
- `CodeContext.overview` - Totals, file type breakdown, flags (Layer 0)
- `CodeContext.files` - Dict of path to `FileContext` (Layer 1+)

**Applied in**: `workflows/buildCodeContextWorkflow.py:88-181`

---

## Risk Scoring Pattern

Files are scored by multiple risk factors to prioritize review effort.

**Factors** (`activities/prioritizeFiles.py:34-144`):
- Lines changed (base score)
- Sensitive path keywords (config, auth, api, etc.)
- File extension (code files > docs)
- Production vs test code
- New files get bonus score
- Large changes get exponential scaling

**Pattern**: Score each factor, sum them, return (score, reasons) tuple.

---

## Agent Factory Pattern

Agents are created through a factory that accepts configuration dictionaries.

**Pattern**: Static factory methods that build configured agent instances.

**Example** (`agents/base.py:8-42`):
```python
class AgentFactory:
    @staticmethod
    def create_agent(model, mcp_servers, allowed_tools, system_prompt, max_turns, add_dirs):
        options = ClaudeAgentOptions(...)
        return ClaudeSDKClient(options=options)

    @staticmethod
    def create_from_config(config: dict):
        return AgentFactory.create_agent(**config)
```

**Applied in**:
- `agents/base.py` - Factory implementation
- `config/calcAgentConfig.py` - Config dict provider
- `config/codeAnalysisAgentConfig.py` - Config dict provider

---

## Git Reference Resolution Pattern

The codebase handles multiple git reference formats uniformly.

**Supported formats**:
- Branch names: `main`, `feature/foo`
- Tags: `v1.0.0`
- Full SHA: `abc123...` (40 chars)
- Short SHA: `abc123` (7+ chars)
- Relative refs: `main~3`, `HEAD^2`

**Pattern**: Check format with regex, resolve to full SHA when possible.

**Applied in**:
- `activities/resolveCloneable.py:48-63` - `is_relative_reference()`
- `activities/resolveCloneable.py:110-181` - `resolve_reference_to_commit_sha()`
- `activities/cloneRepo.py:21-41` - Clone handling for each format
