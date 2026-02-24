import logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from ..config import get_settings
from . import templates

logger = logging.getLogger("email.service")


def _send(to_email: str, subject: str, html_content: str) -> None:
    settings = get_settings()

    if not settings.sendgrid_api_key or not settings.sendgrid_from_email:
        logger.warning("SendGrid not configured — skipping email send")
        return

    message = Mail(
        from_email=settings.sendgrid_from_email,
        to_emails=to_email,
        subject=subject,
        html_content=html_content,
    )

    try:
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        sg.send(message)
        logger.info(f"Email '{subject}' sent to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        raise


def send_verification_email(first_name: str, to_email: str, raw_token: str, frontend_url: str) -> None:
    verify_url = f"{frontend_url}/verify-email?token={raw_token}"
    html = templates.verification_email(first_name=first_name, verify_url=verify_url)
    _send(to_email=to_email, subject="Verify your Linguini email", html_content=html)


def send_reset_password_email(first_name: str, to_email: str, raw_token: str, frontend_url: str) -> None:
    reset_url = f"{frontend_url}/reset-password?token={raw_token}"
    html = templates.reset_password_email(first_name=first_name, reset_url=reset_url)
    _send(to_email=to_email, subject="Reset your Linguini password", html_content=html)
