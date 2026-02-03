"""
Git Integration for LookML Deployment.

Handles:
1. Cloning/updating Looker Git repository
2. Creating branches for enrichment changes
3. Committing generated LookML files
4. Creating Pull Requests via GitHub API
5. Triggering Looker validation (optional)
"""

import os
import subprocess
import tempfile
import shutil
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from pathlib import Path

import httpx


@dataclass
class GitConfig:
    """Configuration for Git operations."""
    repo_url: str  # e.g., https://github.com/org/looker-models.git
    default_branch: str = "main"
    views_path: str = "views"  # Path within repo for view files
    github_token: Optional[str] = None  # For PR creation

    @classmethod
    def from_env(cls) -> "GitConfig":
        """Load config from environment variables."""
        return cls(
            repo_url=os.getenv("LOOKER_GIT_REPO_URL", ""),
            default_branch=os.getenv("LOOKER_GIT_DEFAULT_BRANCH", "main"),
            views_path=os.getenv("LOOKER_GIT_VIEWS_PATH", "views"),
            github_token=os.getenv("GITHUB_TOKEN"),
        )


@dataclass
class PRResult:
    """Result of PR creation."""
    success: bool
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    branch_name: Optional[str] = None
    error: Optional[str] = None
    files_changed: List[str] = None

    def __post_init__(self):
        if self.files_changed is None:
            self.files_changed = []


@dataclass
class CommitInfo:
    """Information about a commit."""
    sha: str
    message: str
    author: str
    timestamp: str
    files: List[str]


class GitOperations:
    """
    Handles Git operations for LookML deployment.

    Uses subprocess for Git commands (works without GitPython dependency).
    """

    def __init__(self, config: GitConfig):
        self.config = config
        self.work_dir: Optional[Path] = None
        self._temp_dir: Optional[str] = None

    def _run_git(self, *args, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
        """Run a git command."""
        cmd = ["git"] + list(args)
        result = subprocess.run(
            cmd,
            cwd=cwd or self.work_dir,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise GitError(f"Git command failed: {' '.join(cmd)}\n{result.stderr}")
        return result

    def clone_or_update(self, target_dir: Optional[str] = None) -> Path:
        """
        Clone the repository or update if it exists.

        Args:
            target_dir: Optional directory to clone into. Uses temp dir if not provided.

        Returns:
            Path to the repository directory.
        """
        if target_dir:
            self.work_dir = Path(target_dir)
        else:
            self._temp_dir = tempfile.mkdtemp(prefix="looker_git_")
            self.work_dir = Path(self._temp_dir)

        repo_name = self.config.repo_url.split("/")[-1].replace(".git", "")
        repo_path = self.work_dir / repo_name

        if repo_path.exists():
            # Update existing repo
            self._run_git("fetch", "--all", cwd=repo_path)
            self._run_git("checkout", self.config.default_branch, cwd=repo_path)
            self._run_git("pull", cwd=repo_path)
        else:
            # Clone fresh
            self._run_git("clone", self.config.repo_url, str(repo_path), cwd=self.work_dir)

        self.work_dir = repo_path
        return repo_path

    def create_branch(self, branch_name: str) -> str:
        """
        Create and checkout a new branch.

        Args:
            branch_name: Name for the new branch

        Returns:
            Full branch name
        """
        # Ensure we're on the default branch first
        self._run_git("checkout", self.config.default_branch)
        self._run_git("pull")

        # Create and checkout new branch
        try:
            self._run_git("checkout", "-b", branch_name)
        except GitError:
            # Branch might exist, try to checkout
            self._run_git("checkout", branch_name)
            self._run_git("pull", "origin", branch_name)

        return branch_name

    def write_lookml_file(self, filename: str, content: str) -> Path:
        """
        Write a LookML file to the views directory.

        Args:
            filename: Name of the file (e.g., "my_view.view.lkml")
            content: LookML content

        Returns:
            Path to the written file
        """
        views_dir = self.work_dir / self.config.views_path
        views_dir.mkdir(parents=True, exist_ok=True)

        file_path = views_dir / filename
        file_path.write_text(content)

        return file_path

    def commit_changes(self, message: str, files: Optional[List[str]] = None) -> CommitInfo:
        """
        Stage and commit changes.

        Args:
            message: Commit message
            files: Optional list of specific files to stage. Stages all if not provided.

        Returns:
            CommitInfo with details about the commit
        """
        if files:
            for f in files:
                self._run_git("add", f)
        else:
            self._run_git("add", "-A")

        # Check if there are changes to commit
        status = self._run_git("status", "--porcelain")
        if not status.stdout.strip():
            raise GitError("No changes to commit")

        self._run_git("commit", "-m", message)

        # Get commit info
        log = self._run_git("log", "-1", "--format=%H|%s|%an|%ai")
        parts = log.stdout.strip().split("|")

        # Get changed files
        diff = self._run_git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
        changed_files = diff.stdout.strip().split("\n") if diff.stdout.strip() else []

        return CommitInfo(
            sha=parts[0],
            message=parts[1],
            author=parts[2],
            timestamp=parts[3],
            files=changed_files
        )

    def push_branch(self, branch_name: str) -> None:
        """
        Push branch to remote.

        Args:
            branch_name: Branch to push
        """
        self._run_git("push", "-u", "origin", branch_name)

    def cleanup(self) -> None:
        """Clean up temporary directory if created."""
        if self._temp_dir and os.path.exists(self._temp_dir):
            shutil.rmtree(self._temp_dir)
            self._temp_dir = None


class GitHubPRCreator:
    """
    Creates Pull Requests via GitHub API.
    """

    def __init__(self, token: str, repo_owner: str, repo_name: str):
        self.token = token
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.api_base = "https://api.github.com"

    @classmethod
    def from_repo_url(cls, repo_url: str, token: str) -> "GitHubPRCreator":
        """Create from repository URL."""
        # Parse URL like https://github.com/owner/repo.git
        parts = repo_url.rstrip(".git").split("/")
        repo_name = parts[-1]
        repo_owner = parts[-2]
        return cls(token, repo_owner, repo_name)

    def create_pull_request(
        self,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
        draft: bool = False,
        labels: Optional[List[str]] = None,
        reviewers: Optional[List[str]] = None,
    ) -> PRResult:
        """
        Create a Pull Request.

        Args:
            title: PR title
            body: PR description/body
            head_branch: Branch with changes
            base_branch: Target branch (usually main)
            draft: Create as draft PR
            labels: Optional labels to add
            reviewers: Optional reviewers to request

        Returns:
            PRResult with PR details
        """
        url = f"{self.api_base}/repos/{self.repo_owner}/{self.repo_name}/pulls"

        headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
        }

        payload = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch,
            "draft": draft,
        }

        try:
            with httpx.Client() as client:
                response = client.post(url, headers=headers, json=payload)

                if response.status_code == 201:
                    data = response.json()
                    pr_number = data["number"]

                    # Add labels if provided
                    if labels:
                        self._add_labels(pr_number, labels, headers)

                    # Request reviewers if provided
                    if reviewers:
                        self._request_reviewers(pr_number, reviewers, headers)

                    return PRResult(
                        success=True,
                        pr_url=data["html_url"],
                        pr_number=pr_number,
                        branch_name=head_branch,
                    )
                else:
                    return PRResult(
                        success=False,
                        error=f"GitHub API error: {response.status_code} - {response.text}"
                    )
        except Exception as e:
            return PRResult(success=False, error=str(e))

    def _add_labels(self, pr_number: int, labels: List[str], headers: dict) -> None:
        """Add labels to a PR."""
        url = f"{self.api_base}/repos/{self.repo_owner}/{self.repo_name}/issues/{pr_number}/labels"
        with httpx.Client() as client:
            client.post(url, headers=headers, json={"labels": labels})

    def _request_reviewers(self, pr_number: int, reviewers: List[str], headers: dict) -> None:
        """Request reviewers for a PR."""
        url = f"{self.api_base}/repos/{self.repo_owner}/{self.repo_name}/pulls/{pr_number}/requested_reviewers"
        with httpx.Client() as client:
            client.post(url, headers=headers, json={"reviewers": reviewers})

    def get_pr_status(self, pr_number: int) -> Dict[str, Any]:
        """Get status of a PR including checks."""
        url = f"{self.api_base}/repos/{self.repo_owner}/{self.repo_name}/pulls/{pr_number}"
        headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
        }

        with httpx.Client() as client:
            response = client.get(url, headers=headers)
            if response.status_code == 200:
                return response.json()
            return {"error": response.text}


class GitError(Exception):
    """Custom exception for Git operations."""
    pass


class LookMLDeployer:
    """
    High-level interface for deploying LookML changes.

    Orchestrates Git operations and PR creation.
    """

    def __init__(self, config: GitConfig):
        self.config = config
        self.git = GitOperations(config)
        self.pr_creator: Optional[GitHubPRCreator] = None

        if config.github_token and config.repo_url:
            self.pr_creator = GitHubPRCreator.from_repo_url(
                config.repo_url,
                config.github_token
            )

    def deploy_lookml(
        self,
        table_name: str,
        lookml_content: str,
        enrichment_summary: Dict[str, Any],
        create_pr: bool = True,
        draft: bool = True,
        labels: Optional[List[str]] = None,
    ) -> PRResult:
        """
        Deploy generated LookML to Git and optionally create PR.

        Args:
            table_name: Name of the table/view
            lookml_content: Generated LookML content
            enrichment_summary: Summary of enrichments for PR description
            create_pr: Whether to create a PR
            draft: Create as draft PR
            labels: Labels to add to PR

        Returns:
            PRResult with deployment details
        """
        try:
            # Generate branch name
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            branch_name = f"enrichment/{table_name}/{timestamp}"

            # Clone/update repo
            self.git.clone_or_update()

            # Create branch
            self.git.create_branch(branch_name)

            # Write LookML file
            filename = f"{table_name}.view.lkml"
            file_path = self.git.write_lookml_file(filename, lookml_content)

            # Commit
            commit_message = self._generate_commit_message(table_name, enrichment_summary)
            commit_info = self.git.commit_changes(commit_message)

            # Push
            self.git.push_branch(branch_name)

            # Create PR if requested
            if create_pr and self.pr_creator:
                pr_title = f"[AI Enrichment] {table_name}"
                pr_body = self._generate_pr_body(table_name, enrichment_summary, commit_info)

                result = self.pr_creator.create_pull_request(
                    title=pr_title,
                    body=pr_body,
                    head_branch=branch_name,
                    base_branch=self.config.default_branch,
                    draft=draft,
                    labels=labels or ["ai-enrichment", "lookml"],
                )
                result.files_changed = commit_info.files
                return result
            else:
                return PRResult(
                    success=True,
                    branch_name=branch_name,
                    files_changed=commit_info.files,
                )

        except Exception as e:
            return PRResult(success=False, error=str(e))
        finally:
            self.git.cleanup()

    def _generate_commit_message(self, table_name: str, summary: Dict[str, Any]) -> str:
        """Generate commit message from enrichment summary."""
        lines = [
            f"Enrich {table_name} metadata via AI agent",
            "",
            "Changes:",
        ]

        if summary.get("labels_added"):
            lines.append(f"- Added {summary['labels_added']} labels")
        if summary.get("descriptions_added"):
            lines.append(f"- Added {summary['descriptions_added']} descriptions")
        if summary.get("sensitivity_tags"):
            lines.append(f"- Added {summary['sensitivity_tags']} sensitivity tags")

        lines.extend([
            "",
            "Generated by Semantic Enrichment Agent",
        ])

        return "\n".join(lines)

    def _generate_pr_body(
        self,
        table_name: str,
        summary: Dict[str, Any],
        commit_info: CommitInfo
    ) -> str:
        """Generate PR description."""
        body = f"""## Summary

AI-powered metadata enrichment for `{table_name}`.

### Enrichment Statistics

| Metric | Count |
|--------|-------|
| Labels Added | {summary.get('labels_added', 0)} |
| Descriptions Added | {summary.get('descriptions_added', 0)} |
| Sensitivity Tags | {summary.get('sensitivity_tags', 0)} |
| Total Columns | {summary.get('total_columns', 0)} |

### Files Changed

"""
        for f in commit_info.files:
            body += f"- `{f}`\n"

        body += """
### Review Checklist

- [ ] Labels are business-friendly and accurate
- [ ] Descriptions clearly explain column purpose
- [ ] Sensitivity classifications are correct
- [ ] No sensitive data exposed in descriptions

### Test Plan

1. Deploy to dev environment
2. Verify dimensions/measures appear correctly in Looker
3. Check that labels display properly in Explore
4. Validate SQL generation works

---

🤖 Generated by [Semantic Enrichment Agent](https://github.com/bardbyte/agent-looker-poc)
"""
        return body


# ============================================================================
# Mock Implementation for Demo
# ============================================================================

class MockGitDeployer:
    """
    Mock deployer for demo purposes when Git is not configured.
    """

    def __init__(self):
        self.deployments: List[Dict[str, Any]] = []

    def deploy_lookml(
        self,
        table_name: str,
        lookml_content: str,
        enrichment_summary: Dict[str, Any],
        create_pr: bool = True,
        draft: bool = True,
        labels: Optional[List[str]] = None,
    ) -> PRResult:
        """Simulate deployment."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        branch_name = f"enrichment/{table_name}/{timestamp}"

        # Store for display
        self.deployments.append({
            "table_name": table_name,
            "branch_name": branch_name,
            "lookml_content": lookml_content,
            "summary": enrichment_summary,
            "timestamp": datetime.now().isoformat(),
        })

        # Simulate PR URL
        mock_pr_number = len(self.deployments)
        mock_pr_url = f"https://github.com/example/looker-models/pull/{mock_pr_number}"

        return PRResult(
            success=True,
            pr_url=mock_pr_url,
            pr_number=mock_pr_number,
            branch_name=branch_name,
            files_changed=[f"views/{table_name}.view.lkml"],
        )


def get_deployer(config: Optional[GitConfig] = None) -> LookMLDeployer | MockGitDeployer:
    """
    Factory function to get appropriate deployer.

    Returns real deployer if configured, mock otherwise.
    """
    if config and config.repo_url and config.github_token:
        return LookMLDeployer(config)
    return MockGitDeployer()
