import resend

from src.config import settings


async def send_verification_email(to_email: str, verify_url: str) -> None:
    resend.api_key = settings.resend_api_key
    resend.Emails.send({
        "from": "Signals <noreply@watchsignal.app>",
        "to": [to_email],
        "subject": "Verify your Signals account",
        "html": f"""
            <p>Thanks for signing up for Signals.</p>
            <p>Click the link below to verify your email address:</p>
            <p><a href="{verify_url}">{verify_url}</a></p>
            <p>This link will remain active until you verify.</p>
        """,
    })
