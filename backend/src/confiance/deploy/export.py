import difflib
import json
from pathlib import Path

from .base import Change, DeployResult, Deployer, register


@register("export")
class ExportDeployer(Deployer):
    """Writes a change package (new files, unified diffs, ops) for the client to apply themselves."""

    def deploy(self, changes: list[Change], *, label: str, message: str) -> DeployResult:
        root = (Path(self.config.get("out_dir", "./data/exports")) / label).resolve()
        root.mkdir(parents=True, exist_ok=True)
        manifest = []
        for c in changes:
            slug = f"page-{c.page_id}"
            (root / f"{slug}.new.html").write_text(c.new_html)
            diff = "".join(difflib.unified_diff(c.old_html.splitlines(True), c.new_html.splitlines(True),
                                                f"a/{c.source_path or c.url}", f"b/{c.source_path or c.url}"))
            (root / f"{slug}.diff").write_text(diff)
            manifest.append({"page_id": c.page_id, "url": c.url, "source_path": c.source_path,
                             "proposal_id": c.proposal_id, "rationale": c.rationale})
        (root / "HOW_TO_APPLY.txt").write_text(
            "These are the improvements CONFIANCE suggests for your website.\n\n"
            "For each page there is a file ending in .new.html (the improved page) and a .diff file that shows exactly\n"
            "what changed. Send this folder to whoever looks after your website and ask them to update the pages.\n"
            "Nothing has been changed on your live website.\n")
        (root / "manifest.json").write_text(json.dumps({"message": message, "changes": manifest}, indent=2))
        return DeployResult("draft_open", str(root), {"files": len(changes)})
