from __future__ import annotations

import base64
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Device, EmailToken, User, utcnow
from app.security import hash_password, hash_token, issue_device_token, issue_web_token


ROOT = Path(__file__).resolve().parents[2]


class AccountProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)

        class TestConfig(Config):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{(root / 'account.db').as_posix()}"
            SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"check_same_thread": False}}
            VAULT_STORAGE_DIR = root / "vaults"
            MAIL_DEV_CONSOLE = True
            SMTP_HOST = ""
            SMTP_PASSWORD = ""

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.device_token, self.web_token = self._seed()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.tmp.cleanup()

    def _seed(self) -> tuple[str, str]:
        with self.app.app_context():
            user = User(email="owner@example.com", password_hash=hash_password("website-password-12"), is_verified=True)
            db.session.add(user)
            db.session.flush()
            first = Device(user_id=user.id, name="pc", platform="test", client_version="0.9.1", token_hash="pending")
            second = Device(user_id=user.id, name="other", platform="test", client_version="0.9.0", token_hash="other")
            db.session.add_all([first, second])
            db.session.flush()
            token = issue_device_token(user, first)
            first.token_hash = hash_token(token)
            web = issue_web_token(user)
            db.session.commit()
            self.user_id = user.id
            self.keep_device_id = second.id
            self.revoke_device_id = first.id
            return token, web

    def _establish(self):
        res = self.client.put(
            "/api/sync/commit",
            json={
                "purpose": "establish",
                "expectedKeyVersion": 0,
                "expectedVaultVersion": 0,
                "dataBase64": base64.b64encode(b"vault-v1").decode("ascii"),
                "wrappedKeyBase64": base64.b64encode(b"wrap-v1").decode("ascii"),
            },
            headers={"Authorization": f"Bearer {self.device_token}"},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))

    def test_pages_separate_password_unbind_and_client_rotation(self):
        account = (ROOT / "frontend/src/pages/AccountPage.tsx").read_text(encoding="utf-8")
        forgot = (ROOT / "frontend/src/pages/ForgotPage.tsx").read_text(encoding="utf-8")
        verify = (ROOT / "frontend/src/pages/ForgotVerifyPage.tsx").read_text(encoding="utf-8")
        for text in (account, forgot, verify):
            self.assertIn("改网站密码" if text is account else "只重置网站登录密码", text)
            self.assertIn("解绑", text)
            self.assertIn("桌面客户端", text)
            self.assertNotIn(".kpkey", text.lower())
            self.assertNotIn('type="file"', text)
            self.assertNotIn("/sync/commit", text)
        self.assertIn('to="/forgot"', account)
        self.assertNotIn("更换云端密钥", account)
        me_rules = {rule.rule for rule in self.app.url_map.iter_rules() if rule.rule.startswith("/api/me")}
        self.assertEqual(
            me_rules,
            {
                "/api/me",
                "/api/me/request-code",
                "/api/me/devices/<int:device_id>/revoke",
                "/api/me/binding-key/regenerate",
                "/api/me/delete",
            },
        )

    def test_website_session_cannot_rotate_and_unbind_keeps_key(self):
        self._establish()
        headers = {"Authorization": f"Bearer {self.web_token}"}
        blocked = self.client.put(
            "/api/sync/commit",
            json={
                "purpose": "rotate",
                "expectedKeyVersion": 1,
                "expectedVaultVersion": 1,
                "dataBase64": base64.b64encode(b"vault-new").decode("ascii"),
                "wrappedKeyBase64": base64.b64encode(b"wrap-new").decode("ascii"),
            },
            headers=headers,
        )
        self.assertEqual(blocked.status_code, 401)
        missing = self.client.post("/api/me/rotate-key", json={"dataBase64": base64.b64encode(b"nope").decode("ascii")}, headers=headers)
        self.assertEqual(missing.status_code, 404)
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            password_hash = user.password_hash
            code = "654321"
            db.session.add(
                EmailToken(
                    user_id=user.id,
                    purpose="unbind_device",
                    code_hash=hash_token(code),
                    expires_at=utcnow() + timedelta(minutes=10),
                )
            )
            db.session.commit()
        revoked = self.client.post(f"/api/me/devices/{self.revoke_device_id}/revoke", json={"code": code}, headers=headers)
        self.assertEqual(revoked.status_code, 200)
        self.assertNotIn("website-password-12", revoked.get_data(as_text=True))
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            self.assertEqual(user.key_version, 1)
            self.assertEqual(user.wrapped_kpkey, b"wrap-v1")
            self.assertEqual(user.password_hash, password_hash)
            self.assertIsNotNone(db.session.get(Device, self.revoke_device_id).revoked_at)
            self.assertIsNone(db.session.get(Device, self.keep_device_id).revoked_at)

    def test_reset_mail_does_not_equate_password_unbind_and_rotation(self):
        from unittest.mock import patch

        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            code = "123456"
            db.session.add(
                EmailToken(
                    user_id=user.id,
                    purpose="reset",
                    code_hash=hash_token(code),
                    expires_at=utcnow() + timedelta(minutes=10),
                )
            )
            db.session.commit()
        with patch("app.api.auth.send_mail") as send_mail:
            res = self.client.post(
                "/api/auth/reset",
                json={"email": "owner@example.com", "code": code, "newPassword": "another-password-12"},
            )
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("another-password-12", res.get_data(as_text=True))
        body = send_mail.call_args.args[2]
        self.assertNotIn("another-password-12", body)
        self.assertIn("网站登录密码已重置", body)
        self.assertIn("个人中心单独操作", body)
        self.assertIn("桌面客户端", body)
        self.assertNotIn(".kpkey", body.lower())


if __name__ == "__main__":
    unittest.main()
