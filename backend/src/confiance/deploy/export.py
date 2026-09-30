import difflib
import json
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from .base import Change, DeployResult, Deployer, register


@register("export")
class ExportDeployer(Deployer):
    """Writes a change package (new files, unified diffs, ops) for the client to apply themselves."""

    def deploy(self, changes: list[Change], *, label: str, message: str, extras: dict[str, str] | None = None) -> DeployResult:
        root = (Path(self.config.get("out_dir", "./data/exports")) / label).resolve()
        if root.exists():
            shutil.rmtree(root)  # a re-export must not carry stale files from an earlier package with the same label
        root.mkdir(parents=True, exist_ok=True)
        manifest = []
        for c in changes:
            path = urlsplit(c.url).path
            slug = path.strip("/").replace("/", "__") or "home"
            if c.is_new:
                (root / "new-pages").mkdir(exist_ok=True)
                (root / "new-pages" / f"{slug}.html").write_text(c.new_html)
                files = [f"new-pages/{slug}.html"]
            else:
                (root / "pages").mkdir(exist_ok=True)
                (root / "pages" / f"{slug}.new.html").write_text(c.new_html)
                diff = "".join(difflib.unified_diff(c.old_html.splitlines(True), c.new_html.splitlines(True), f"a/{c.source_path or c.url}", f"b/{c.source_path or c.url}"))
                (root / "pages" / f"{slug}.diff").write_text(diff)
                files = [f"pages/{slug}.new.html", f"pages/{slug}.diff"]
            manifest.append({"page_id": c.page_id, "url": c.url, "path": path, "new_page": c.is_new, "source_path": c.source_path, "proposal_id": c.proposal_id, "rationale": c.rationale, "files": files})
        for rel, content in (extras or {}).items():
            target = (root / rel).resolve()
            if not str(target).startswith(str(root)):
                continue  # never write outside the package
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        (root / "HOW_TO_APPLY.txt").write_text(
            "These are the improvements CONFIANCE suggests for your website. Nothing on your live website has been changed.\n\n"
            "pages/        an improved version of each existing page (.new.html) and a .diff showing exactly what changed\n"
            "new-pages/    brand-new pages to add to your site at the path shown in manifest.json\n"
            "site-files/   files for the top of your site, such as llms.txt and sitemap.xml (check each one before publishing)\n"
            "report.html   the full report, including the prioritized improvement plan (open it in a browser; print it to save as a PDF)\n\n"
            "Send this folder to whoever looks after your website. After publishing, start a new round in Confiance to measure the effect.\n")
        (root / "manifest.json").write_text(json.dumps({"message": message, "changes": manifest}, indent=2))
        return DeployResult("draft_open", str(root), {"files": len(changes), "extras": sorted((extras or {}))})
