from __future__ import annotations

import smtplib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.config import Config
from app.mail import MailError, send_mail


class FakeSMTP:
    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_args = None
        self.sent = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, msg):
        self.sent = msg


class MailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "mail-test.db"

        class TestConfig(Config):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path.as_posix()}"
            MAIL_DEV_CONSOLE = True
            SMTP_HOST = ""
            SMTP_PORT = 587
            SMTP_USERNAME = ""
            SMTP_PASSWORD = ""
            SMTP_FROM = "noreply@example.com"
            SMTP_USE_TLS = True
            SMTP_USE_SSL = False

        self.app = create_app(TestConfig)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dev_console_without_host_does_not_raise(self):
        with self.app.app_context():
            send_mail("user@example.com", "subj", "body")

    def test_missing_host_without_console_raises(self):
        self.app.config["MAIL_DEV_CONSOLE"] = False
        with self.app.app_context():
            with self.assertRaises(MailError) as ctx:
                send_mail("user@example.com", "subj", "body")
        self.assertIn("SMTP_HOST", ctx.exception.public_message)

    def test_configured_host_sends_even_if_console_flag_on(self):
        self.app.config["SMTP_HOST"] = "smtp.163.com"
        self.app.config["SMTP_USERNAME"] = "your_account@163.com"
        self.app.config["SMTP_PASSWORD"] = "not-a-real-secret"
        self.app.config["MAIL_DEV_CONSOLE"] = True
        fake = FakeSMTP("smtp.163.com", 587, timeout=30)
        with self.app.app_context():
            with patch("app.mail.smtplib.SMTP", return_value=fake) as ctor:
                send_mail("user@example.com", "验证码", "code")
        ctor.assert_called_once()
        self.assertEqual(ctor.call_args.args[:2], ("smtp.163.com", 587))
        self.assertTrue(fake.started_tls)
        self.assertEqual(fake.login_args, ("your_account@163.com", "not-a-real-secret"))
        self.assertEqual(fake.sent["To"], "user@example.com")

    def test_ssl_skips_starttls(self):
        self.app.config["SMTP_HOST"] = "smtp.163.com"
        self.app.config["SMTP_PORT"] = 465
        self.app.config["SMTP_USE_SSL"] = True
        self.app.config["SMTP_USE_TLS"] = True
        fake = FakeSMTP("smtp.163.com", 465, timeout=30)
        with self.app.app_context():
            with patch("app.mail.smtplib.SMTP_SSL", return_value=fake) as ctor:
                with patch("app.mail.smtplib.SMTP") as plain:
                    send_mail("user@example.com", "subj", "body")
        ctor.assert_called_once()
        plain.assert_not_called()
        self.assertFalse(fake.started_tls)

    def test_smtp_failure_is_mail_error(self):
        self.app.config["SMTP_HOST"] = "smtp.163.com"
        self.app.config["MAIL_DEV_CONSOLE"] = False

        class Boom(FakeSMTP):
            def send_message(self, msg):
                raise smtplib.SMTPAuthenticationError(535, b"auth fail")

        with self.app.app_context():
            with patch("app.mail.smtplib.SMTP", return_value=Boom("smtp.163.com", 587)):
                with self.assertRaises(MailError) as ctx:
                    send_mail("user@example.com", "subj", "body")
        self.assertIn("认证未通过", ctx.exception.public_message)

    def test_forgot_returns_503_when_mail_fails(self):
        client = self.app.test_client()
        with self.app.app_context():
            from app.extensions import db
            from app.models import User
            from app.security import hash_password

            user = User.query.filter_by(email="reset@example.com").first()
            if user is None:
                user = User(
                    email="reset@example.com",
                    password_hash=hash_password("long-password-12"),
                    is_verified=True,
                )
                db.session.add(user)
                db.session.commit()

        def boom(*_args, **_kwargs):
            raise MailError("邮件发送失败：SMTP 认证未通过。请检查发件账号与授权码（不是登录密码）。")

        with patch("app.tokens.send_mail", side_effect=boom):
            res = client.post("/api/auth/forgot", json={"email": "reset@example.com"})
        self.assertEqual(res.status_code, 503)
        self.assertIn("邮件发送失败", res.get_json()["error"])

    def test_forgot_unknown_email_still_ok(self):
        client = self.app.test_client()
        res = client.post("/api/auth/forgot", json={"email": "nobody@example.com"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])

    def test_register_returns_503_when_mail_fails(self):
        client = self.app.test_client()
        with self.app.app_context():
            from app.extensions import db
            from app.models import User

            User.query.filter_by(email="new-user@example.com").delete()
            db.session.commit()

        def boom(*_args, **_kwargs):
            raise MailError("邮件发送失败：无法连接 SMTP 服务器。")

        with patch("app.tokens.send_mail", side_effect=boom):
            res = client.post(
                "/api/auth/register",
                json={"email": "new-user@example.com", "password": "long-password-12"},
            )
        self.assertEqual(res.status_code, 503)
        body = res.get_json()
        self.assertIn("邮件发送失败", body["error"])
        self.assertTrue(body.get("needVerify"))

    def test_resend_verify_returns_503_when_mail_fails(self):
        client = self.app.test_client()
        with self.app.app_context():
            from app.extensions import db
            from app.models import User
            from app.security import hash_password

            User.query.filter_by(email="pending@example.com").delete()
            db.session.add(
                User(
                    email="pending@example.com",
                    password_hash=hash_password("long-password-12"),
                    is_verified=False,
                )
            )
            db.session.commit()

        def boom(*_args, **_kwargs):
            raise MailError("邮件发送失败：无法连接 SMTP 服务器。")

        with patch("app.tokens.send_mail", side_effect=boom):
            res = client.post("/api/auth/resend-verify", json={"email": "pending@example.com"})
        self.assertEqual(res.status_code, 503)
        self.assertIn("邮件发送失败", res.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
