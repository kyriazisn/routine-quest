import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

log = logging.getLogger("rq.mailer")

# Captured links for tests and local development (console mailer only)
outbox: list[tuple[str, str]] = []


def send_magic_link(email: str, link: str) -> None:
    s = get_settings()
    if s.mailer == "console":
        if s.env == "prod":
            raise RuntimeError("console mailer is not allowed in production")
        outbox.append((email, link))
        log.warning("MAGIC LINK for %s: %s", email, link)
        return

    msg = EmailMessage()
    msg["Subject"] = "Σύνδεση στο Routine Quest"
    msg["From"] = s.smtp_from
    msg["To"] = email
    msg.set_content(
        "Γεια σου!\n\n"
        f"Πάτα τον σύνδεσμο για να συνδεθείς (ισχύει {s.magic_link_ttl_min} λεπτά):\n{link}\n\n"
        "Αν δεν το ζήτησες εσύ, αγνόησε αυτό το μήνυμα.\n"
    )
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
        smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)
