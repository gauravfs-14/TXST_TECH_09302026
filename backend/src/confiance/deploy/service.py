"""Deployment orchestration: approval gate, stale-base protection, snapshots, rollback."""

from sqlalchemy import select

from .. import audit, snapshots
from ..db import session_scope
from ..models import ChangeProposal, Deployment, Page, Project, Run
from . import Change, build_deployer


class DeployError(RuntimeError):
    pass


def _set_live(s, page: Page, version_id: int) -> None:
    page.live_version_id = version_id


def _package_extras(run_id: int) -> dict[str, str]:
    """The report and the plan's site files, bundled with the approved page changes."""
    from .. import reports
    from ..models import PlanAction

    extras: dict[str, str] = {}
    try:
        rep = reports.build(run_id)
        extras["report.html"], extras["report.md"] = reports.render_html(rep), reports.render_markdown(rep)
    except Exception:
        pass  # a report problem must never block deploying approved changes
    with session_scope() as s:
        for a in s.scalars(select(PlanAction).where(PlanAction.run_id == run_id)):
            fn = (a.draft or {}).get("filename")
            if fn and (a.draft or {}).get("content") and "/" not in fn and ".." not in fn and a.status != "dismissed":
                extras[f"site-files/{fn}"] = a.draft["content"]
    return extras


def deploy_run(run_id: int, actor: str = "user") -> int:
    with session_scope() as s:
        run = s.get(Run, run_id)
        project = s.get(Project, run.project_id)
        props = list(s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == run_id,
                                                            ChangeProposal.status == "approved")))
        if not props:
            raise DeployError("no approved proposals for this run")
        changes, versions = [], {}
        for cp in props:
            page = s.get(Page, cp.page_id)
            if page.live_version_id != cp.base_version_id:
                raise DeployError(f"page {page.url} changed since the proposal was made; re-run the optimizer "
                                  f"(refusing to overwrite newer content)")
            changes.append(Change(page.id, page.url, page.source_path, snapshots.live_content(s, page) or "",
                                  snapshots.version_content(s, cp.candidate_version_id), cp.id, cp.rationale, is_new=bool(page.is_new)))
            versions[str(page.id)] = {"from": cp.base_version_id, "to": cp.candidate_version_id}
        cfg = project.deploy_config or {"type": "export"}
        message = f"CONFIANCE run {run_id}: GEO improvements for {project.name}\n\n" + "\n".join(
            f"- {c.url}: {c.rationale}" for c in changes)
        project_id = project.id
    audit.record("deploy.started", actor, {"deployer": cfg.get("type"), "pages": len(changes)},
                 project_id=project_id, run_id=run_id)
    result = build_deployer(cfg).deploy(changes, label=f"run-{run_id}", message=message, extras=_package_extras(run_id))
    with session_scope() as s:
        dep = Deployment(project_id=project_id, run_id=run_id, kind="deploy", deployer=cfg.get("type", "export"),
                         status=result.status, external_ref=result.external_ref, versions=versions,
                         details=result.details)
        s.add(dep)
        s.flush()
        if result.status != "failed":
            for cp in s.scalars(select(ChangeProposal).where(ChangeProposal.run_id == run_id,
                                                              ChangeProposal.status == "approved")):
                cp.status = "deployed"
        dep_id = dep.id
    audit.record("deploy.finished", actor, {"deployment_id": dep_id, "status": result.status,
                                            "ref": result.external_ref}, project_id=project_id, run_id=run_id)
    if result.status == "applied":
        confirm_live(dep_id, actor="system")
    return dep_id


def confirm_live(deployment_id: int, actor: str = "user") -> None:
    """Called when the change is actually live (PR merged / CMS published). Moves the live pointer."""
    with session_scope() as s:
        dep = s.get(Deployment, deployment_id)
        if dep.status == "failed":
            raise DeployError("deployment failed; nothing to confirm")
        if dep.kind == "rollback":
            is_rollback = True
        else:
            is_rollback = False
    if is_rollback:
        confirm_rollback_live(deployment_id, actor)
        return
    with session_scope() as s:
        dep = s.get(Deployment, deployment_id)
        for pid, v in dep.versions.items():
            _set_live(s, s.get(Page, int(pid)), v["to"])
        dep.status = "applied"
        project_id, run_id = dep.project_id, dep.run_id
    audit.record("deploy.live_confirmed", actor, {"deployment_id": deployment_id},
                 project_id=project_id, run_id=run_id)


def rollback(deployment_id: int, actor: str = "user") -> int:
    with session_scope() as s:
        dep = s.get(Deployment, deployment_id)
        if dep.kind != "deploy" or dep.status != "applied":
            raise DeployError("only applied deployments can be rolled back")
        project = s.get(Project, dep.project_id)
        changes, versions = [], {}
        for pid, v in dep.versions.items():
            page = s.get(Page, int(pid))
            if page.live_version_id != v["to"]:
                raise DeployError(f"page {page.url} has been changed since this deployment; roll back the newer one first")
            changes.append(Change(page.id, page.url, page.source_path, snapshots.version_content(s, v["to"]),
                                  snapshots.version_content(s, v["from"]), None, "rollback"))
            versions[pid] = {"from": v["to"], "to": v["from"]}
        cfg = project.deploy_config or {"type": "export"}
        project_id, run_id = project.id, dep.run_id
    audit.record("rollback.started", actor, {"deployment_id": deployment_id}, project_id=project_id, run_id=run_id)
    result = build_deployer(cfg).deploy(changes, label=f"rollback-{deployment_id}",
                                        message=f"CONFIANCE rollback of deployment {deployment_id}")
    with session_scope() as s:
        rb = Deployment(project_id=project_id, run_id=run_id, kind="rollback", deployer=cfg.get("type", "export"),
                        status=result.status, external_ref=result.external_ref, versions=versions,
                        details=result.details)
        s.add(rb)
        s.flush()
        rb_id = rb.id
    audit.record("rollback.finished", actor, {"rollback_id": rb_id, "status": result.status},
                 project_id=project_id, run_id=run_id)
    if result.status == "applied":
        confirm_rollback_live(rb_id)
    return rb_id


def confirm_rollback_live(rollback_id: int, actor: str = "system") -> None:
    with session_scope() as s:
        rb = s.get(Deployment, rollback_id)
        for pid, v in rb.versions.items():
            page = s.get(Page, int(pid))
            new = snapshots.new_version(s, page, snapshots.version_content(s, v["to"]), "rollback",
                                        parent_id=page.live_version_id, run_id=rb.run_id,
                                        note=f"rollback of deployment {rollback_id}")
            page.live_version_id = new.id
        rb.status = "applied"
        project_id = rb.project_id
        original = next((d for d in s.scalars(select(Deployment).where(Deployment.project_id == project_id,
                                                                       Deployment.kind == "deploy",
                                                                       Deployment.status == "applied"))
                         if d.versions and {k: x["to"] for k, x in d.versions.items()} ==
                         {k: x["from"] for k, x in rb.versions.items()}), None)
        if original:
            original.status = "rolled_back"
    audit.record("rollback.live_confirmed", actor, {"rollback_id": rollback_id}, project_id=project_id)
