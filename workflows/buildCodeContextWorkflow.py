from temporalio import workflow
from datetime import timedelta
from temporalio.common import RetryPolicy
from utils.dataclasses import (
    RepoHandle, ChangeSet, ChangedFile, Hunk,
    CodeContext, ContextOverview, Totals, FileTypeStats, FileContext, ContextMetadata,
    PrioritizedFile, FileSummary
)
from activities.prioritizeFiles import prioritize_files
from activities.summarizeFile import summarize_file
from collections import defaultdict
from dataclasses import asdict
import json

@workflow.defn(name="buildCodeContextWorkflow")
class BuildCodeContextWorkflow:
    """
    Workflow to efficiently manage context and tokens before giving the agent exactly what it needs.
    This workflow processes the repository handle and changeset to build an optimized code context.
    """
    
    @workflow.run
    async def run(self, repo_handle: RepoHandle, change_set: ChangeSet) -> CodeContext:
        """
        Build code context from repository handle and changeset.
        
        Args:
            repo_handle: Dictionary with repo_id, repo_path, and commit_sha (Temporal serializes dataclasses to dicts)
            change_set: Dictionary with base_commit, head_commit, and files (Temporal serializes dataclasses to dicts)
            
        Returns:
            CodeContext dataclass containing overview (Layer 0) and prioritized files (Layer 1+)
        """
        
        workflow.logger.info(f"Building code context for repo: {repo_handle.repo_id}")
        workflow.logger.info(f"Processing changeset with {len(change_set.files)} changed files")
        
        # Calculate totals
        total_lines_added = sum(f.added for f in change_set.files)
        total_lines_removed = sum(f.removed for f in change_set.files)
        total_hunks = sum(len(f.hunks) for f in change_set.files)
        files_added = sum(1 for f in change_set.files if f.added > 0 and f.removed == 0)
        files_deleted = sum(1 for f in change_set.files if f.removed > 0 and f.added == 0)
        
        # Build file type breakdown
        file_type_stats = defaultdict(lambda: {"count": 0, "lines_added": 0, "lines_removed": 0})
        
        def get_file_type(file_path: str) -> str:
            """Get file type from extension"""
            if '.' in file_path:
                ext = file_path.rsplit('.', 1)[-1].lower()
                return f".{ext}"
            # No extension - check if it's a special file
            if '/' in file_path:
                return "unknown"
            # Could be a file without extension (like README, Dockerfile, etc.)
            return "no_extension"
        
        for file in change_set.files:
            file_type = get_file_type(file.path)
            file_type_stats[file_type]["count"] += 1
            file_type_stats[file_type]["lines_added"] += file.added
            file_type_stats[file_type]["lines_removed"] += file.removed
        
        # Convert to FileTypeStats dataclasses
        file_breakdown = {
            file_type: FileTypeStats(
                count=stats["count"],
                lines_added=stats["lines_added"],
                lines_removed=stats["lines_removed"]
            )
            for file_type, stats in file_type_stats.items()
        }
        
        # Calculate flags
        flags = []
        if files_added > 0:
            flags.append("has_new_files")
        if files_deleted > 0:
            flags.append("has_deleted_files")
        if total_lines_added > 1000 or total_lines_removed > 1000:
            flags.append("large_change")
        if len(change_set.files) > 50:
            flags.append("many_files_changed")
        if total_hunks > 200:
            flags.append("many_hunks")
        
        # Build ContextOverview (Layer 0)
        totals = Totals(
            files_changed=len(change_set.files),
            files_added=files_added,
            files_deleted=files_deleted,
            lines_added=total_lines_added,
            lines_removed=total_lines_removed,
            total_hunks=total_hunks
        )
        
        overview = ContextOverview(
            totals=totals,
            file_breakdown=file_breakdown,
            flags=flags
        )
        
        workflow.logger.info(f"Context layer 0: {totals.files_changed} files, "
                           f"+{totals.lines_added}/-{totals.lines_removed} lines, "
                           f"{len(file_breakdown)} file types")
        
        # Step 2: Prioritize files by importance
        # Temporal automatically serializes dataclasses to dicts when passing to activities
        workflow.logger.info("Prioritizing files by risk score...")
        prioritized_files = await workflow.execute_activity(
            prioritize_files,
            args=[change_set],
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=2)
        )
      
        workflow.logger.info(f"Prioritized {len(prioritized_files)} files (after filtering ignored files)")
        if prioritized_files:
            # Handle both dict (after Temporal serialization) and PrioritizedFile object
            first_file = prioritized_files[0]
            workflow.logger.info(f"Top file: {first_file.path} (risk score: {first_file.risk_score:.2f})")
        
        # Step 3: Summarize each prioritized file
        workflow.logger.info("Summarizing prioritized files...")
        summarizer_version = "v1"  # Can be made configurable in the future
        
        # Create a lookup map from change_set to get added/removed values
        file_stats_map = {f.path: (f.added, f.removed) for f in change_set.files}
        
        # Build files dict (Layer 1+) - map file paths to FileContext
        # Handle both dict (after Temporal serialization) and PrioritizedFile object
        files_dict = {}
        for file_data in prioritized_files:
            # Already a PrioritizedFile object
            file_path = file_data.path
            risk_score = file_data.risk_score
            reasons = file_data.reasons
            # Get added/removed from original change_set
            added, removed = file_stats_map.get(file_path, (0, 0))
            
            # Summarize the file
            try:
                summary = await workflow.execute_activity(
                    summarize_file,
                    args=[repo_handle.repo_id, repo_handle.commit_sha, file_path, repo_handle.repo_path, summarizer_version],
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=2)
                )
            except Exception as e:
                workflow.logger.warning(f"Failed to summarize {file_path}: {e}")
                summary = None
            
            file_context = FileContext(
                path=file_path,
                risk_score=risk_score,
                added=added,
                removed=removed,
                reasons=reasons,
                summary=summary
            )
            files_dict[file_path] = file_context
        
        # Build and return CodeContext
        code_context = CodeContext(
            repo_id=repo_handle.repo_id,
            base_commit=change_set.base_commit,
            head_commit=change_set.head_commit,
            overview=overview,
            files=files_dict,
            metadata=ContextMetadata()
        )

        return code_context