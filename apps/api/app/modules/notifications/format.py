"""Channel presentation for approved notification copy.

In-app stays plain text. Email adds an HTML alternative and Slack adds Block Kit.
Both are built from the same facts, subject and action link. Values are escaped.
"""

from __future__ import annotations

import html
import re
from typing import Any

_URL_PREFIXES = ("http://", "https://")
_CODE = re.compile(r"\b(\d{6})\b")


def clean_subject_detail(rendered: str) -> str:
    parts = [part.strip(" —-\t") for part in rendered.split("·")]
    return " · ".join(part for part in parts if part)


def presentation_from_copy(copy: dict[str, Any], safe: dict[str, str]) -> dict[str, Any]:
    intro = str(copy.get("intro") or "").format_map(safe).strip()
    footer = str(copy.get("footer") or "").format_map(safe).strip()
    action_label = str(copy.get("action_label") or "Open Sahyog").format_map(safe).strip()
    action_url = safe.get("action_url") or ""
    if not action_url.startswith(_URL_PREFIXES):
        action_url = ""
    facts: list[dict[str, str]] = []
    for item in copy.get("facts") or []:
        key = str(item.get("key") or "")
        if key not in safe:
            raise KeyError(key)
        value = (safe.get(key) or "").strip()
        if not value:
            continue
        label = str(item.get("label") or key).strip()
        suffix = str(item.get("suffix") or "")
        facts.append({"label": label, "value": f"{value}{suffix}"})
    return {
        "intro": intro,
        "footer": footer,
        "action_label": action_label or "Open Sahyog",
        "action_url": action_url,
        "facts": facts,
    }


def plain_body(presentation: dict[str, Any]) -> str:
    parts: list[str] = []
    intro = str(presentation.get("intro") or "").strip()
    if intro:
        parts.append(intro)
    fact_lines = [
        f"{item['label']}: {item['value']}"
        for item in presentation.get("facts") or []
        if item.get("label") and item.get("value")
    ]
    if fact_lines:
        parts.append("\n".join(fact_lines))
    footer = str(presentation.get("footer") or "").strip()
    if footer:
        parts.append(footer)
    action_url = str(presentation.get("action_url") or "").strip()
    if action_url:
        label = str(presentation.get("action_label") or "Open").strip()
        parts.append(f"{label}: {action_url}")
    return "\n\n".join(parts).strip()


def email_html(subject: str, body: str, presentation: dict[str, Any] | None) -> str:
    if presentation:
        return _rich_email(subject, presentation)
    return _plain_email(subject, body)


def slack_message(
    subject: str, body: str, presentation: dict[str, Any] | None
) -> dict[str, Any]:
    blocks = (
        _rich_slack_blocks(subject, presentation)
        if presentation
        else _plain_slack_blocks(subject, body)
    )
    text = f"{subject}\n{body}".strip() if subject else body
    payload: dict[str, Any] = {
        "text": text[:3000],
        "unfurl_links": False,
        "unfurl_media": False,
    }
    if blocks:
        payload["blocks"] = blocks
    return payload


def _rich_email(subject: str, presentation: dict[str, Any]) -> str:
    intro = _html_text(str(presentation.get("intro") or ""))
    footer = _html_text(str(presentation.get("footer") or ""))
    rows: list[str] = []
    for index, item in enumerate(presentation.get("facts") or []):
        background = "#f4f7f8" if index % 2 == 0 else "#ffffff"
        rows.append(
            "<tr>"
            f'<td style="padding:8px 12px;background:{background};color:#5c6b73;'
            'width:34%;font-size:13px;vertical-align:top;">'
            f"{html.escape(str(item.get('label') or ''))}</td>"
            f'<td style="padding:8px 12px;background:{background};font-size:14px;'
            'font-weight:600;vertical-align:top;">'
            f"{_html_text(str(item.get('value') or ''))}</td></tr>"
        )
    facts_html = ""
    if rows:
        facts_html = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="margin:16px 0 8px;border-collapse:collapse;border:1px solid #e2e8f0;">'
            f"{''.join(rows)}</table>"
        )
    action = _button(
        str(presentation.get("action_url") or ""),
        str(presentation.get("action_label") or "Open Sahyog"),
    )
    inner = (
        f'<p style="margin:0 0 12px;font-size:15px;line-height:1.5;">{intro}</p>'
        f"{facts_html}"
        f'<p style="margin:12px 0 16px;font-size:14px;line-height:1.5;color:#334155;">{footer}</p>'
        f"{action}"
    )
    return _shell(subject, inner)


def _plain_email(subject: str, body: str) -> str:
    code = _CODE.search(body)
    paragraphs = [
        f'<p style="margin:0 0 12px;font-size:15px;line-height:1.5;">{_html_text(part)}</p>'
        for part in body.split("\n\n")
        if part.strip()
    ]
    code_html = ""
    if code:
        code_html = (
            '<p style="margin:16px 0;font-size:28px;letter-spacing:0.28em;font-weight:700;'
            'font-family:ui-monospace,Menlo,Consolas,monospace;">'
            f"{html.escape(code.group(1))}</p>"
        )
    return _shell(subject, code_html + "".join(paragraphs))


def _shell(subject: str, inner: str) -> str:
    safe_subject = html.escape(subject)
    return (
        "<!DOCTYPE html><html><body style=\"margin:0;background:#f4f6f8;"
        "font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1c2430;\">"
        f'<div style="display:none;max-height:0;overflow:hidden;">{safe_subject}</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        '<tr><td align="center" style="padding:24px 12px;">'
        '<table role="presentation" width="560" cellpadding="0" cellspacing="0" '
        'style="max-width:560px;width:100%;background:#ffffff;border:1px solid #e2e8f0;'
        'border-radius:12px;">'
        '<tr><td style="background:#0f3d4c;color:#ffffff;padding:16px 24px;'
        'font-size:13px;letter-spacing:0.08em;">SAHYOG</td></tr>'
        '<tr><td style="padding:24px;">'
        f'<h1 style="margin:0 0 12px;font-size:20px;line-height:1.3;">{safe_subject}</h1>'
        f"{inner}</td></tr>"
        '<tr><td style="padding:12px 24px 20px;color:#64748b;font-size:12px;'
        'line-height:1.4;">Operational notice from Sahyog. No clinical notes are included.'
        "</td></tr></table></td></tr></table></body></html>"
    )


def _button(url: str, label: str) -> str:
    if not url.startswith(_URL_PREFIXES):
        return ""
    return (
        f'<a href="{html.escape(url, quote=True)}" '
        'style="display:inline-block;background:#0f3d4c;color:#ffffff;text-decoration:none;'
        'padding:12px 18px;border-radius:8px;font-size:14px;font-weight:600;">'
        f"{html.escape(label or 'Open Sahyog')}</a>"
    )


def _html_text(value: str) -> str:
    return html.escape(value).replace("\n", "<br>")


def _slack_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rich_slack_blocks(subject: str, presentation: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [_header(subject)]
    intro = str(presentation.get("intro") or "").strip()
    if intro:
        blocks.append(_section(_slack_escape(intro)[:3000]))
    fields = []
    for item in (presentation.get("facts") or [])[:10]:
        label = _slack_escape(str(item.get("label") or ""))
        value = _slack_escape(str(item.get("value") or ""))
        if not label or not value:
            continue
        fields.append({"type": "mrkdwn", "text": f"*{label}*\n{value}"[:2000]})
    if fields:
        blocks.append({"type": "section", "fields": fields})
    footer = str(presentation.get("footer") or "").strip()
    if footer:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": _slack_escape(footer)[:2000]}],
            }
        )
    action_url = str(presentation.get("action_url") or "")
    if action_url.startswith(_URL_PREFIXES):
        label = str(presentation.get("action_label") or "Open Sahyog").strip() or "Open Sahyog"
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": label[:75], "emoji": False},
                        "url": action_url,
                        "style": "primary",
                    }
                ],
            }
        )
    return blocks


def _plain_slack_blocks(subject: str, body: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if subject.strip():
        blocks.append(_header(subject))
    text = body.strip()
    code = _CODE.search(text)
    if code:
        text = f"`{code.group(1)}`\n{text}"
    if text:
        blocks.append(_section(_slack_escape(text)[:3000]))
    return blocks


def _header(subject: str) -> dict[str, Any]:
    text = " ".join(subject.split())[:150] or "Sahyog"
    return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": False}}


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text or "Sahyog"}}
