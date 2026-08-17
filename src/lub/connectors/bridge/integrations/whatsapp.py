# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""WhatsApp Business API integration for the Bradesco Bridge platform.

Provides webhook parsing for inbound messages and an HTTP client for
sending replies via the WhatsApp Cloud API. Supports text, image, and
voice message types.

The module is intentionally dependency-light: it uses only ``httpx``
(already a transitive dependency of the ``openai`` package) for HTTP
calls and the stdlib for everything else.

Requires: ``pip install httpx``

Usage::

    from lub.connectors.bridge.integrations.whatsapp import WhatsAppClient

    client = WhatsAppClient(
        phone_number_id="1234567890",
        access_token="EAAx...",
    )
    msg = client.parse_webhook(payload)
    client.send_text(to=msg.sender, text="Sua transferencia foi realizada.")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

_LOG = structlog.get_logger("lub.integrations.whatsapp")

_MISSING_MSG = (
    "The 'httpx' package is required for WhatsAppClient. Install it with: pip install httpx"
)

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

_API_BASE = "https://graph.facebook.com/v19.0"


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


class MessageType(StrEnum):
    """Supported WhatsApp message types."""

    TEXT = "text"
    IMAGE = "image"
    VOICE = "voice"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class InboundMessage:
    """A parsed inbound WhatsApp message.

    Attributes:
        sender: Sender phone number in E.164 format.
        text: Message text content (empty for non-text types).
        message_type: Type of the message (text, image, voice).
        timestamp: UTC timestamp when the message was sent.
        message_id: WhatsApp message identifier.
        media_url: URL to download the media (for image/voice messages).
        metadata: Additional fields from the webhook payload.
    """

    sender: str
    text: str
    message_type: MessageType
    timestamp: datetime
    message_id: str = ""
    media_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_text(self) -> bool:
        """Return ``True`` if this is a text message."""
        return self.message_type == MessageType.TEXT

    def is_media(self) -> bool:
        """Return ``True`` if this is an image or voice message."""
        return self.message_type in (MessageType.IMAGE, MessageType.VOICE)


# ---------------------------------------------------------------------------
# Webhook parsing errors
# ---------------------------------------------------------------------------


class WebhookParseError(ValueError):
    """Raised when a webhook payload cannot be parsed."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


@dataclass
class WhatsAppClient:
    """WhatsApp Business Cloud API client.

    Parses inbound webhook payloads and sends outbound messages (text,
    image, voice) via the Meta Graph API.

    Args:
        phone_number_id: The WhatsApp Business phone number ID.
        access_token: A valid Graph API access token.
        api_base: Base URL for the Graph API (override for testing).
        timeout: HTTP request timeout in seconds.
    """

    phone_number_id: str
    access_token: str
    api_base: str = _API_BASE
    timeout: float = 15.0
    _http: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if httpx is None:
            raise ImportError(_MISSING_MSG)
        self._http = httpx.Client(
            base_url=f"{self.api_base}/{self.phone_number_id}",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )
        _LOG.info(
            "whatsapp.init",
            phone_number_id=self.phone_number_id,
        )

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    def parse_webhook(self, payload: dict[str, Any]) -> InboundMessage:
        """Parse a WhatsApp Cloud API webhook payload into an :class:`InboundMessage`.

        Handles the nested structure of the webhook payload and extracts
        the first message from the first change entry.

        Args:
            payload: The raw webhook JSON payload as a dictionary.

        Returns:
            An :class:`InboundMessage` representing the first message
            in the payload.

        Raises:
            WebhookParseError: If the payload structure is invalid or
                contains no messages.
        """
        try:
            entry = payload["entry"][0]
            changes = entry["changes"][0]
            value = changes["value"]
            messages = value.get("messages", [])
        except (KeyError, IndexError, TypeError) as exc:
            raise WebhookParseError(f"Invalid webhook payload structure: {exc}") from exc

        if not messages:
            raise WebhookParseError("Webhook payload contains no messages.")

        msg = messages[0]
        msg_type_raw = msg.get("type", "unknown")

        try:
            message_type = MessageType(msg_type_raw)
        except ValueError:
            message_type = MessageType.UNKNOWN

        sender = msg.get("from", "")
        message_id = msg.get("id", "")

        # Extract text
        text = ""
        if message_type == MessageType.TEXT:
            text = msg.get("text", {}).get("body", "")

        # Extract media URL
        media_url = ""
        if message_type in (MessageType.IMAGE, MessageType.VOICE):
            media_section = msg.get(msg_type_raw, {})
            media_id = media_section.get("id", "")
            if media_id:
                media_url = f"{self.api_base}/{media_id}"

        # Parse timestamp
        ts_raw = msg.get("timestamp", "")
        try:
            timestamp = datetime.fromtimestamp(int(ts_raw), tz=UTC)
        except (ValueError, TypeError, OSError):
            timestamp = datetime.now(tz=UTC)

        # Extract contacts metadata
        contacts = value.get("contacts", [])
        contact_name = ""
        if contacts:
            profile = contacts[0].get("profile", {})
            contact_name = profile.get("name", "")

        inbound = InboundMessage(
            sender=sender,
            text=text,
            message_type=message_type,
            timestamp=timestamp,
            message_id=message_id,
            media_url=media_url,
            metadata={"contact_name": contact_name, "raw_type": msg_type_raw},
        )

        _LOG.info(
            "whatsapp.inbound",
            sender=sender,
            message_type=message_type.value,
            text_len=len(text),
        )

        return inbound

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    def send_text(self, to: str, text: str) -> bool:
        """Send a text message to a WhatsApp user.

        Args:
            to: Recipient phone number in E.164 format.
            text: Message body.

        Returns:
            ``True`` if the message was accepted by the API,
            ``False`` otherwise.
        """
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        return self._send(body, to=to, msg_type="text")

    def send_image(self, to: str, image_url: str, caption: str = "") -> bool:
        """Send an image message to a WhatsApp user.

        Args:
            to: Recipient phone number in E.164 format.
            image_url: Public URL of the image.
            caption: Optional image caption.

        Returns:
            ``True`` if the message was accepted by the API.
        """
        image_payload: dict[str, Any] = {"link": image_url}
        if caption:
            image_payload["caption"] = caption

        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "image",
            "image": image_payload,
        }
        return self._send(body, to=to, msg_type="image")

    def send_voice(self, to: str, audio_url: str) -> bool:
        """Send a voice/audio message to a WhatsApp user.

        Args:
            to: Recipient phone number in E.164 format.
            audio_url: Public URL of the audio file (OGG/Opus).

        Returns:
            ``True`` if the message was accepted by the API.
        """
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "audio",
            "audio": {"link": audio_url},
        }
        return self._send(body, to=to, msg_type="voice")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _send(self, body: dict[str, Any], *, to: str, msg_type: str) -> bool:
        """Send an outbound message and return success status."""
        try:
            response = self._http.post("/messages", json=body)
            if response.status_code in (200, 201):
                _LOG.info(
                    "whatsapp.sent",
                    to=to,
                    msg_type=msg_type,
                    status=response.status_code,
                )
                return True
            _LOG.warning(
                "whatsapp.send_failed",
                to=to,
                msg_type=msg_type,
                status=response.status_code,
                body=response.text[:200],
            )
            return False
        except Exception as exc:
            _LOG.error(
                "whatsapp.send_error",
                to=to,
                msg_type=msg_type,
                error=str(exc),
            )
            return False


__all__ = ["InboundMessage", "MessageType", "WebhookParseError", "WhatsAppClient"]
