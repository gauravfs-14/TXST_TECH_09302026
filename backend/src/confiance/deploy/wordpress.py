import os

import httpx

from .base import Change, DeployResult, Deployer, register


@register("wordpress")
class WordPressDeployer(Deployer):
    """CMS connector for WordPress via the REST API (application-password auth).

    config: base_url, user, app_password_env (env var name holding the password), publish (default false).
    A page's `source_path` holds its REST route, e.g. "pages/42". By default the edit is saved as an
    autosave (a draft revision an editor reviews in wp-admin); set publish=true to update live content.
    `new_html` is the page's editable content (the CMS content body), which is what the crawler stores
    for WordPress projects."""

    def _client(self) -> httpx.Client:
        pw = os.environ.get(self.config.get("app_password_env", "WP_APP_PASSWORD"), "")
        return httpx.Client(base_url=self.config["base_url"].rstrip("/") + "/wp-json/wp/v2/",
                            auth=(self.config["user"], pw), timeout=30,
                            transport=self.config.get("_transport"))

    def deploy(self, changes: list[Change], *, label: str, message: str, extras: dict[str, str] | None = None) -> DeployResult:
        publish = bool(self.config.get("publish", False))
        applied, errors = [], {}
        with self._client() as c:
            for ch in changes:
                if not ch.source_path:
                    errors[ch.url] = "no source_path (REST route) configured"
                    continue
                route = ch.source_path if publish else f"{ch.source_path}/autosaves"
                r = c.post(route, json={"content": ch.new_html})
                if r.status_code >= 300:
                    errors[ch.url] = f"{r.status_code}: {r.text[:200]}"
                else:
                    applied.append(ch.url)
        if errors and not applied:
            return DeployResult("failed", None, {"errors": errors})
        return DeployResult("applied" if publish else "draft_open", label,
                            {"updated": applied, "errors": errors, "published": publish})
