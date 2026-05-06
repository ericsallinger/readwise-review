"""Email sending: Gmail SMTP, multipart message, mocked smtplib."""

from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from readwise_review.email_render import RenderedEmail
from readwise_review.email_send import send_email


def test_send_email_constructs_multipart_message_and_uses_ssl_smtp() -> None:
    rendered = RenderedEmail(subject="hello", html="<p>hi</p>", plain="hi")

    with patch("readwise_review.email_send.smtplib.SMTP_SSL") as smtp_cls:
        smtp = MagicMock()
        smtp_cls.return_value.__enter__.return_value = smtp
        send_email(
            rendered,
            from_email="from@example.com",
            to_email="to@example.com",
            gmail_app_password="pw",
        )

    smtp_cls.assert_called_once_with("smtp.gmail.com", 465)
    smtp.login.assert_called_once_with("from@example.com", "pw")
    smtp.send_message.assert_called_once()

    sent_msg: EmailMessage = smtp.send_message.call_args.args[0]
    assert sent_msg["Subject"] == "hello"
    assert sent_msg["From"] == "from@example.com"
    assert sent_msg["To"] == "to@example.com"
    assert sent_msg.is_multipart()
    parts = list(sent_msg.iter_parts())
    plain = next(p for p in parts if p.get_content_type() == "text/plain")
    html = next(p for p in parts if p.get_content_type() == "text/html")
    assert plain.get_content().strip() == "hi"
    assert html.get_content().strip() == "<p>hi</p>"
