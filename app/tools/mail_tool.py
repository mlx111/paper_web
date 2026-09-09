"""Email tool — sends email via core/mail.py, marked as high-risk (ask_user).

This tool is registered with permission="ask_user" so the HITL layer
intercepts it and requires human approval before execution.

For safety in the container demo environment, actual SMTP sending is
gated behind a setting. When SMTP is disabled (default), the tool
returns a simulated success result.
"""

from __future__ import annotations

import os

from langchain.tools import tool

from .tool_result import ToolResult


@tool(
    name_or_callable="send_email",
    description=(
        "Send an email to a specified recipient. "
        "This is a high-risk operation that requires human approval. "
        "Args: to (email address), subject (str), body (str)"
    ),
)
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email. Returns ToolResult JSON."""
    # Safety: in demo/container environment, don't actually send SMTP
    smtp_enabled = os.getenv("MAIL_SMTP_ENABLED", "false").lower() == "true"

    if smtp_enabled:
        try:
            from core.mail import create_mail_instance
            from fastapi_mail.schemas import MessageSchema
            import asyncio

            mailer = create_mail_instance()
            message = MessageSchema(
                subject=subject,
                recipients=[to],
                body=body,
                subtype="plain",
            )
            asyncio.run(mailer.send_message(message))
        except Exception as exc:
            return ToolResult.failure(
                f"Failed to send email: {exc}", "TOOL_FAILED"
            ).to_message_content()

    # Simulated success (demo mode)
    return ToolResult.success(
        data={
            "to": to,
            "subject": subject,
            "body_preview": body[:100],
            "smtp_sent": smtp_enabled,
            "message": "Email prepared and approved. "
                       + ("SMTP sent." if smtp_enabled else "Simulated (SMTP disabled in demo)."),
        },
        summary=f"email to {to}: {subject}",
    ).to_message_content()
