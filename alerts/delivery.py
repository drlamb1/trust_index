"""
EdgeFinder — Alert Delivery (Phase 4)

Delivers alerts and daily briefings via multiple channels.
Channels: Email (SMTP), Slack (webhook), Discord (webhook), ntfy.sh (push).

All delivery is async and non-blocking.
Failed deliveries are logged but never raise — the caller always gets a
result dict: {"email": True, "slack": False, ...}.

Entry point:
    results = await deliver(subject, content_md)
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from config.settings import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Markdown → HTML helper
# ---------------------------------------------------------------------------

_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC = re.compile(r"\*(.+?)\*")
_MD_CODE = re.compile(r"`(.+?)`")
_MD_H1 = re.compile(r"^# (.+)$", re.MULTILINE)
_MD_H2 = re.compile(r"^## (.+)$", re.MULTILINE)
_MD_H3 = re.compile(r"^### (.+)$", re.MULTILINE)
_MD_HR = re.compile(r"^[═─=\-]{3,}$", re.MULTILINE)
_MD_UL = re.compile(r"^[•\-\*] (.+)$", re.MULTILINE)


def _md_to_html(md: str) -> str:
    """Convert a subset of Markdown to HTML suitable for email bodies."""
    html = md
    html = _MD_H1.sub(r"<h1>\1</h1>", html)
    html = _MD_H2.sub(r"<h2>\1</h2>", html)
    html = _MD_H3.sub(r"<h3>\1</h3>", html)
    html = _MD_BOLD.sub(r"<strong>\1</strong>", html)
    html = _MD_ITALIC.sub(r"<em>\1</em>", html)
    html = _MD_CODE.sub(r"<code>\1</code>", html)
    html = _MD_HR.sub(r"<hr>", html)
    html = _MD_UL.sub(r"<li>\1</li>", html)

    # Wrap consecutive <li> in <ul>
    html = re.sub(r"(<li>.*?</li>)(\n<li>.*?</li>)+", lambda m: f"<ul>{m.group(0)}</ul>", html)

    # Paragraphs: blank-line-separated blocks not already in tags
    lines = html.split("\n")
    out, buf = [], []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if buf:
                block = " ".join(buf)
                if not block.startswith("<"):
                    block = f"<p>{block}</p>"
                out.append(block)
                buf = []
        else:
            buf.append(stripped)
    if buf:
        block = " ".join(buf)
        if not block.startswith("<"):
            block = f"<p>{block}</p>"
        out.append(block)

    body = "\n".join(out)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 720px; margin: 40px auto; color: #1a1a1a; line-height: 1.6; }}
  h1, h2, h3 {{ color: #0d6efd; }}
  code {{ background: #f0f0f0; padding: 2px 5px; border-radius: 3px;
         font-family: 'Courier New', monospace; }}
  hr {{ border: none; border-top: 2px solid #dee2e6; margin: 20px 0; }}
  li {{ margin: 4px 0; }}
  p {{ margin: 8px 0; }}
</style>
</head>
<body>
{body}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


async def send_email(subject: str, content_md: str) -> bool:
    """Send an email via SMTP using aiosmtplib. Returns True on success."""
    if not all([settings.smtp_host, settings.smtp_user, settings.smtp_password, settings.alert_email_to]):
        logger.debug("Email delivery skipped: SMTP not configured")
        return False

    try:
        import aiosmtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = settings.alert_email_to

        msg.attach(MIMEText(content_md, "plain", "utf-8"))
        msg.attach(MIMEText(_md_to_html(content_md), "html", "utf-8"))

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=True,
        )
        logger.info("Email delivered: %s → %s", subject, settings.alert_email_to)
        return True

    except Exception as exc:
        logger.error("Email delivery failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------


async def send_slack(subject: str, content_md: str) -> bool:
    """POST a message to a Slack incoming webhook. Returns True on success."""
    if not settings.slack_webhook_url:
        logger.debug("Slack delivery skipped: no webhook URL configured")
        return False

    try:
        import httpx

        # Slack renders mrkdwn, so we strip box-drawing chars and send md directly
        text = f"*{subject}*\n\n{content_md}"
        # Slack has a 3000-char limit per block; truncate gracefully
        if len(text) > 2900:
            text = text[:2897] + "…"

        payload = {
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                }
            ]
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.slack_webhook_url, json=payload)
            resp.raise_for_status()

        logger.info("Slack message delivered: %s", subject)
        return True

    except Exception as exc:
        logger.error("Slack delivery failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------


async def send_discord(subject: str, content_md: str) -> bool:
    """POST a message to a Discord webhook. Returns True on success."""
    if not settings.discord_webhook_url:
        logger.debug("Discord delivery skipped: no webhook URL configured")
        return False

    try:
        import httpx

        # Discord embeds support markdown; cap at 4096 chars
        desc = content_md
        if len(desc) > 4000:
            desc = desc[:3997] + "…"

        payload = {
            "embeds": [
                {
                    "title": subject,
                    "description": desc,
                    "color": 0x0D6EFD,  # EdgeFinder blue
                }
            ]
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.discord_webhook_url, json=payload)
            resp.raise_for_status()

        logger.info("Discord message delivered: %s", subject)
        return True

    except Exception as exc:
        logger.error("Discord delivery failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# ntfy.sh
# ---------------------------------------------------------------------------


async def send_ntfy(subject: str, content_md: str) -> bool:
    """Push a notification via ntfy.sh. Returns True on success."""
    if not settings.ntfy_topic:
        logger.debug("ntfy delivery skipped: no topic configured")
        return False

    try:
        import httpx

        url = f"{settings.ntfy_server.rstrip('/')}/{settings.ntfy_topic}"
        # ntfy message body is plain text; strip markdown decorators
        body = re.sub(r"[*_`#]", "", content_md)
        if len(body) > 4096:
            body = body[:4093] + "…"

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                content=body.encode(),
                headers={
                    "Title": subject,
                    "Priority": "default",
                    "Tags": "chart_with_upwards_trend",
                },
            )
            resp.raise_for_status()

        logger.info("ntfy notification delivered: %s → %s", subject, settings.ntfy_topic)
        return True

    except Exception as exc:
        logger.error("ntfy delivery failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def deliver(subject: str, content_md: str) -> dict[str, bool]:
    """
    Deliver a message over all configured channels concurrently.

    Returns a dict of channel → success:
        {"email": True, "slack": False, "discord": True, "ntfy": True}

    Never raises. Failed channels are logged and returned as False.
    """
    email_task = asyncio.create_task(send_email(subject, content_md))
    slack_task = asyncio.create_task(send_slack(subject, content_md))
    discord_task = asyncio.create_task(send_discord(subject, content_md))
    ntfy_task = asyncio.create_task(send_ntfy(subject, content_md))

    email_ok, slack_ok, discord_ok, ntfy_ok = await asyncio.gather(
        email_task, slack_task, discord_task, ntfy_task,
        return_exceptions=False,
    )

    results = {
        "email": bool(email_ok),
        "slack": bool(slack_ok),
        "discord": bool(discord_ok),
        "ntfy": bool(ntfy_ok),
    }

    delivered_to = [ch for ch, ok in results.items() if ok]
    if delivered_to:
        logger.info("Alert delivered via: %s", ", ".join(delivered_to))
    else:
        logger.warning("Alert '%s' — no delivery channels succeeded (check config)", subject)

    return results
