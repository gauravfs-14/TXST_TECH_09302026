import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import Change, DeployResult, Deployer, register


def _git(cwd: str, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


@register("git_pr")
class GitPRDeployer(Deployer):
    """Branch + commit + (optionally) push and open a DRAFT pull request. The user's working tree is never
    touched: work happens in a temporary git worktree. Requires config: repo_path, base_branch.
    Only pages with a `source_path` (a static HTML file in the repo) can be deployed this way;
    framework/CMS sites should use the CMS connector or the export deployer."""

    def deploy(self, changes: list[Change], *, label: str, message: str, extras: dict[str, str] | None = None) -> DeployResult:
        repo = self.config["repo_path"]
        base = self.config.get("base_branch", "main")
        branch = f"confiance/{label}"
        missing = [c.url for c in changes if not c.source_path]
        if missing:
            return DeployResult("failed", None, {"error": f"pages without source_path: {missing}"})
        tmp = tempfile.mkdtemp(prefix="confiance-wt-")
        wt = str(Path(tmp) / "wt")
        try:
            _git(repo, "worktree", "add", "-b", branch, wt, base)
            for c in changes:
                target = (Path(wt) / c.source_path).resolve()
                if not str(target).startswith(str(Path(wt).resolve())):
                    raise RuntimeError(f"source_path escapes repository: {c.source_path}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(c.new_html)
            _git(wt, "add", "-A")
            _git(wt, "-c", "user.name=CONFIANCE", "-c", "user.email=confiance@localhost", "commit", "-m", message)
            sha = _git(wt, "rev-parse", "HEAD")
            details = {"branch": branch, "commit": sha, "pushed": False}
            remote = self.config.get("remote", "origin")
            has_remote = remote in _git(repo, "remote").split()
            if has_remote and self.config.get("push", True):
                _git(wt, "push", "-u", remote, branch)
                details["pushed"] = True
                if self.config.get("open_pr", True) and shutil.which("gh"):
                    r = subprocess.run(["gh", "pr", "create", "--draft", "--base", base, "--head", branch,
                                        "--title", message.splitlines()[0], "--body", message],
                                       cwd=wt, capture_output=True, text=True)
                    if r.returncode == 0:
                        details["pr_url"] = r.stdout.strip().splitlines()[-1]
                    else:
                        details["pr_error"] = r.stderr.strip()[:300]
            return DeployResult("draft_open", details.get("pr_url") or branch, details)
        except Exception as e:
            return DeployResult("failed", None, {"error": str(e)})
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo, capture_output=True)
            shutil.rmtree(tmp, ignore_errors=True)
