"""Send a RenderedEmail via Gmail SMTP."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from readwise_review.email_render import RenderedEmail


def send_email(
    rendered: RenderedEmail,
    *,
    from_email: str,
    to_email: str,
    gmail_app_password: str,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = rendered.subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(rendered.plain)
    msg.add_alternative(rendered.html, subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(from_email, gmail_app_password)
        smtp.send_message(msg)
