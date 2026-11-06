from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from flask import current_app

log = logging.getLogger(__name__)


class MailError(RuntimeError):
    """发信失败。public_message 可直接返回给用户，不含密钥。"""

    def __init__(self, public_message: str, *, detail: str = "") -> None:
        super().__init__(detail or public_message)
        self.public_message = public_message


def _public_smtp_error(exc: BaseException) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "邮件发送失败：SMTP 认证未通过。请检查发件账号与授权码（不是登录密码）。"
    if isinstance(exc, smtplib.SMTPConnectError):
        return "邮件发送失败：无法连接 SMTP 服务器。"
    if isinstance(exc, smtplib.SMTPHeloError):
        return "邮件发送失败：SMTP 握手失败。"
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "邮件发送失败：收件地址被拒绝。"
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return "邮件发送失败：发件地址被拒绝。163 等邮箱通常要求 SMTP_FROM 与发件账号一致。"
    if isinstance(exc, smtplib.SMTPDataError):
        return "邮件发送失败：SMTP 服务器拒绝了邮件内容。"
    if isinstance(exc, TimeoutError):
        return "邮件发送失败：连接 SMTP 服务器超时。"
    if isinstance(exc, smtplib.SMTPException):
        return "邮件发送失败：SMTP 服务返回错误。"
    if isinstance(exc, OSError):
        return "邮件发送失败：无法连接 SMTP 服务器。"
    return "邮件发送失败，请稍后重试。"


def send_mail(to: str, subject: str, body: str) -> None:
    host = (current_app.config.get("SMTP_HOST") or "").strip()
    dev_console = bool(current_app.config.get("MAIL_DEV_CONSOLE"))

    # 只要配置了 SMTP_HOST 就真实发信，避免生产环境误留 MAIL_DEV_CONSOLE 而伪装成功。
    if host:
        _send_smtp(to, subject, body, host)
        return

    if dev_console:
        log.info("MAIL to=%s subject=%s\n%s", to, subject, body)
        print(f"\n===== DEV MAIL to={to} =====\n{subject}\n{body}\n=====\n", flush=True)
        return

    raise MailError("邮件发送失败：未配置 SMTP_HOST，无法发送验证码。")


def _send_smtp(to: str, subject: str, body: str, host: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = current_app.config["SMTP_FROM"]
    msg["To"] = to
    msg.set_content(body)

    port = int(current_app.config["SMTP_PORT"])
    username = current_app.config.get("SMTP_USERNAME") or ""
    password = current_app.config.get("SMTP_PASSWORD") or ""
    use_tls = bool(current_app.config.get("SMTP_USE_TLS"))
    use_ssl = bool(current_app.config.get("SMTP_USE_SSL"))
    timeout = int(current_app.config.get("SMTP_TIMEOUT", 30))

    try:
        if use_ssl:
            if use_tls:
                log.warning("SMTP_USE_SSL 与 SMTP_USE_TLS 同时开启，使用隐式 TLS，不再 STARTTLS")
            client = smtplib.SMTP_SSL(host, port, timeout=timeout)
        else:
            client = smtplib.SMTP(host, port, timeout=timeout)

        with client as smtp:
            if (not use_ssl) and use_tls:
                smtp.starttls()
            if username:
                smtp.login(username, password)
            smtp.send_message(msg)
    except MailError:
        raise
    except BaseException as exc:
        log.exception("SMTP send failed host=%s port=%s to=%s", host, port, to)
        raise MailError(_public_smtp_error(exc), detail=str(exc)) from exc
