"""
Email Sender — sends the HTML newsletter via Resend.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    success: bool
    sent_count: int
    failed_count: int
    errors: list[str]


class NewsletterSender:
    RESEND_API_URL = "https://api.resend.com/emails"

    def __init__(
        self,
        api_key: str | None = None,
        from_email: str | None = None,
        from_name: str | None = None,
    ):
        self.api_key = api_key or os.getenv("RESEND_API_KEY")
        self.from_email = from_email or os.getenv("FROM_EMAIL", "newsletter@yourdomain.com")
        self.from_name = from_name or os.getenv("FROM_NAME", "HNWI Prospect Intelligence")

        if not self.api_key:
            raise ValueError("RESEND_API_KEY is required")

    @property
    def from_address(self) -> str:
        return f"{self.from_name} <{self.from_email}>"

    def _build_subject(self, date: datetime | None = None) -> str:
        if date is None:
            date = datetime.now(timezone.utc)
        date_str = date.strftime("%d/%m/%Y")
        return f"💎 Top 5 Prospects HNWI — {date_str}"

    def send_to_one(
        self,
        recipient_email: str,
        html_content: str,
        subject: str | None = None,
        date: datetime | None = None,
    ) -> bool:
        """Send newsletter to a single recipient. Returns True on success."""
        if subject is None:
            subject = self._build_subject(date)

        # Personalize unsubscribe placeholder (simple implementation)
        personalized_html = html_content.replace(
            "{{ unsubscribe_url }}",
            f"https://yourapp.streamlit.app/unsubscribe?email={recipient_email}",
        )

        payload = {
            "from": self.from_address,
            "to": [recipient_email],
            "subject": subject,
            "html": personalized_html,
        }

        try:
            resp = requests.post(
                self.RESEND_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            if resp.status_code in (200, 201):
                logger.info(f"Email sent to {recipient_email}")
                return True
            else:
                logger.warning(
                    f"Failed to send to {recipient_email}: "
                    f"HTTP {resp.status_code} — {resp.text[:200]}"
                )
                return False
        except Exception as e:
            logger.error(f"Exception sending to {recipient_email}: {e}")
            return False

    def send_to_many(
        self,
        recipients: list[str],
        html_content: str,
        subject: str | None = None,
        date: datetime | None = None,
    ) -> SendResult:
        """Send newsletter to a list of recipients."""
        if not recipients:
            logger.info("No recipients — skipping send")
            return SendResult(success=True, sent_count=0, failed_count=0, errors=[])

        if subject is None:
            subject = self._build_subject(date)

        sent = 0
        failed = 0
        errors: list[str] = []

        logger.info(f"Sending newsletter to {len(recipients)} recipients...")

        for email in recipients:
            ok = self.send_to_one(email, html_content, subject=subject, date=date)
            if ok:
                sent += 1
            else:
                failed += 1
                errors.append(email)

        logger.info(f"Newsletter sent: {sent} success, {failed} failures")
        return SendResult(
            success=failed == 0,
            sent_count=sent,
            failed_count=failed,
            errors=errors,
        )

    def send_test(self, test_email: str, html_content: str) -> bool:
        """Send a test email to a single address."""
        subject = f"[TEST] {self._build_subject()}"
        return self.send_to_one(test_email, html_content, subject=subject)
