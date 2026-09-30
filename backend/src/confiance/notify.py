"""Alerts: always stored in-app; optionally pushed to Slack and email. Identical alerts inside the
dedupe window are suppressed so a persistent condition doesn't spam."""

import smtplib
from datetime import timedelta
from email.message import EmailMessage

import httpx
from sqlalchemy import select

from . import audit
from .config import get_settings
from .db import session_scope, utcnow
from .models import Alert


def alert(kind: str, severity: str, title: str, body: str = "", project_id: int | None = None,
          dedupe_hours: int = 24) -> int | None:
    with session_scope() as s:
        since = utcnow() - timedelta(hours=dedupe_hours)
        dup = s.scalars(select(Alert).where(Alert.kind == kind, Alert.title == title, Alert.created_at >= since,
                                            Alert.project_id == project_id)).first()
        if dup:
            return None
        a = Alert(project_id=project_id, kind=kind, severity=severity, title=title, body=body)
        s.add(a)
        s.flush()
        alert_id = a.id
    audit.record("alert.raised", "notifier", {"alert_id": alert_id, "kind": kind, "severity": severity, "title": title},
                 project_id=project_id)
    _push(severity, title, body)
    return alert_id


def _push(severity: str, title: str, body: str) -> None:
    cfg = get_settings()
    if cfg.slack_webhook_url:
        try:
            httpx.post(cfg.slack_webhook_url, timeout=10,
                       json={"text": f"*[CONFIANCE {severity.upper()}]* {title}\n{body[:2500]}"})
        except Exception as e:
            audit.record("alert.push_failed", "notifier", {"channel": "slack", "error": str(e)})
    if cfg.smtp_host and cfg.alert_email_to and cfg.alert_email_from:
        try:
            msg = EmailMessage()
            msg["Subject"], msg["From"], msg["To"] = f"[CONFIANCE {severity}] {title}", cfg.alert_email_from, cfg.alert_email_to
            msg.set_content(body or title)
            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=15) as smtp:
                smtp.starttls()
                if cfg.smtp_user:
                    smtp.login(cfg.smtp_user, cfg.smtp_password or "")
                smtp.send_message(msg)
        except Exception as e:
            audit.record("alert.push_failed", "notifier", {"channel": "email", "error": str(e)})
