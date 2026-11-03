"""Outbound notification adapters.

Only approved, non-clinical copy is passed here. Every adapter is real: SMTP,
an HTTP SMS provider, and the Slack Web API. Missing credentials fail closed with a
stable error code; nothing is written to logs except the channel and code.
"""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any

import aiosmtplib
import httpx
from app.core.config import Settings
from app.core.ports import DeliveryError
from app.modules.notifications.format import email_html, slack_message


class EmailAdapter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def configured(self) -> bool:
        return self._settings.smtp_configured and bool(self._settings.email_from)

    async def send(
        self,
        *,
        address: str,
        subject: str,
        body: str,
        attachments: list[dict[str, Any]] | None = None,
        presentation: dict[str, Any] | None = None,
    ) -> str:
        if not self.configured():
            raise DeliveryError("smtp_unconfigured")
        message = EmailMessage()
        message["From"] = self._settings.email_from
        message["To"] = address
        message["Subject"] = subject
        if self._settings.email_reply_to:
            message["Reply-To"] = self._settings.email_reply_to
        message.set_content(body)
        message.add_alternative(email_html(subject, body, presentation), subtype="html")
        for item in attachments or []:
            content = item.get("content")
            filename = str(item.get("filename") or "attachment.bin")
            content_type = str(item.get("content_type") or "application/octet-stream")
            if not isinstance(content, (bytes, bytearray)) or not content:
                continue
            maintype, _, subtype = content_type.partition("/")
            if not subtype:
                maintype, subtype = "application", "octet-stream"
            # Keep subtype free of parameter junk for EmailMessage.add_attachment.
            subtype = subtype.split(";", 1)[0].strip() or "octet-stream"
            message.add_attachment(
                bytes(content),
                maintype=maintype.strip() or "application",
                subtype=subtype,
                filename=filename,
            )
        try:
            response = await aiosmtplib.send(
                message,
                hostname=self._settings.smtp_host,
                port=self._settings.smtp_port,
                username=(
                    self._settings.smtp_username
                    if self._settings.smtp_auth_mode == "password"
                    else None
                ),
                password=(
                    self._settings.smtp_password
                    if self._settings.smtp_auth_mode == "password"
                    else None
                ),
                start_tls=(
                    self._settings.smtp_use_starttls
                    if self._settings.smtp_auth_mode == "password"
                    else False
                ),
                timeout=15,
            )
        except (aiosmtplib.SMTPException, OSError, TimeoutError) as exc:
            raise DeliveryError("smtp_failed") from exc
        if isinstance(response, tuple):
            return ",".join(str(item) for item in response[1]) or "smtp"
        return "smtp"


class SmsAdapter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def configured(self) -> bool:
        return self._settings.sms_configured

    async def send(self, *, address: str, body: str) -> str:
        if not self.configured():
            raise DeliveryError("sms_unconfigured")
        adapter = (self._settings.sms_adapter or "http").strip().lower()
        if adapter == "twilio":
            return await self._send_twilio(address=address, body=body)
        return await self._send_http(address=address, body=body)

    async def _send_http(self, *, address: str, body: str) -> str:
        payload = {
            "to": address,
            "sender": self._settings.sms_from,
            "message": body,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    self._settings.sms_base_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._settings.sms_api_key}"},
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DeliveryError("sms_failed") from exc
        return str(data.get("id") or data.get("message_id") or "sms")

    async def _send_twilio(self, *, address: str, body: str) -> str:
        sid = self._settings.sms_account_sid.strip()
        token = self._settings.sms_auth_token.strip()
        from_number = self._settings.sms_from
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    url,
                    data={"To": address, "From": from_number, "Body": body},
                    auth=(sid, token),
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DeliveryError("sms_failed") from exc
        return str(data.get("sid") or data.get("uri") or "twilio")


class SlackAdapter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def token_for(self, channel: str) -> str:
        if channel == "slack_staff":
            return self._settings.resolved_slack_staff_bot_token
        if channel == "slack_patient":
            return self._settings.resolved_slack_patient_bot_token
        return ""

    def configured(self, channel: str | None = None) -> bool:
        if channel == "slack_staff":
            return self._settings.slack_staff_configured
        if channel == "slack_patient":
            return self._settings.slack_patient_configured
        if channel is None:
            return (
                self._settings.slack_staff_configured or self._settings.slack_patient_configured
            )
        return False

    async def send(
        self,
        *,
        channel: str,
        address: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> str:
        token = self.token_for(channel)
        if not token:
            raise DeliveryError("slack_unconfigured")
        payload: dict[str, Any] = {
            "channel": address,
            "text": text,
            "unfurl_links": False,
            "unfurl_media": False,
        }
        if blocks:
            payload["blocks"] = blocks
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DeliveryError("slack_failed") from exc
        if not data.get("ok"):
            # Keep code stable for retries; detail is not logged (may include channel ids).
            err = str(data.get("error") or "rejected")
            if err in {"channel_not_found", "not_in_channel", "is_archived"}:
                raise DeliveryError("slack_channel_unavailable")
            if err in {"invalid_auth", "token_revoked", "not_authed", "account_inactive"}:
                raise DeliveryError("slack_auth_failed")
            raise DeliveryError("slack_rejected")
        return str(data.get("ts") or "slack")


class NotificationDispatcher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._email = EmailAdapter(settings)
        self._sms = SmsAdapter(settings)
        self._slack = SlackAdapter(settings)

    def configured(self, channel: str) -> bool:
        if channel == "email":
            return self._email.configured()
        if channel == "sms":
            return self._sms.configured()
        if channel in {"slack_staff", "slack_patient"}:
            return self._slack.configured(channel)
        return False

    async def send(
        self,
        *,
        channel: str,
        address: str,
        subject: str,
        body: str,
        attachments: list[dict[str, Any]] | None = None,
        presentation: dict[str, Any] | None = None,
    ) -> str:
        if channel == "email":
            return await self._email.send(
                address=address,
                subject=subject,
                body=body,
                attachments=attachments,
                presentation=presentation,
            )
        if channel == "sms":
            return await self._sms.send(address=address, body=body)
        if channel in {"slack_staff", "slack_patient"}:
            slack = slack_message(subject, body, presentation)
            return await self._slack.send(
                channel=channel,
                address=address,
                text=str(slack["text"]),
                blocks=slack.get("blocks"),
            )
        raise DeliveryError("unknown_channel")
