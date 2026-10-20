from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from flask import current_app

log = logging.getLogger(__name__)


def send_mail(to: str, subject: str, body: str) -> None:
    if current_app.config.get("MAIL_DEV_CONSOLE") or not current_app.config.get("SMTP_HOST"):
        log.info("MAIL to=%s subject=%s\n%s", to, subject, body)
        print(f"\n===== DEV MAIL to={to} =====\n{subject}\n{body}\n=====\n", flush=True)
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = current_app.config["SMTP_FROM"]
    msg["To"] = to
    msg.set_content(body)

    host = current_app.config["SMTP_HOST"]
    port = current_app.config["SMTP_PORT"]
    username = current_app.config["SMTP_USERNAME"]
    password = current_app.config["SMTP_PASSWORD"]
    use_tls = current_app.config["SMTP_USE_TLS"]

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(msg)
