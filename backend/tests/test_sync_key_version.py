from __future__ import annotations

import base64
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from app import create_app, purge_legacy_keys
from app.config import Config
from app.extensions import db
from app.models import Device, EmailToken, User, utcnow
from app.security import hash_password, hash_token, issue_device_token, issue_web_token

KEY_A = "83BD38E247B7"
KEY_B = "0123456789AB"


class SyncKeyVersionTests(unittest.TestCase):
    """1.0.1：服务器只保存密文、密钥代和密钥标识，不保存任何能解开保险库的数据。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)

        class TestConfig(Config):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{(root / 'sync.db').as_posix()}"
            SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"check_same_thread": False}}
            VAULT_STORAGE_DIR = root / "vaults"
            MAIL_DEV_CONSOLE = True
            SMTP_HOST = ""
            SMTP_PASSWORD = ""

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.token = self._seed()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.tmp.cleanup()

    def _seed(self) -> str:
        with self.app.app_context():
            user = User(email="sync@example.com", password_hash=hash_password("website-password-12"), is_verified=True)
            db.session.add(user)
            db.session.flush()
            device = Device(
                user_id=user.id,
                name="pc",
                platform="test",
                client_version="1.0.1",
                token_hash="pending",
            )
            db.session.add(device)
            db.session.flush()
            token = issue_device_token(user, device)
            device.token_hash = hash_token(token)
            db.session.commit()
            self.user_id = user.id
            return token

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _commit(self, purpose, key, vault, key_id=KEY_A, blob=b"vault-v1", wrap=None):
        body = {
            "purpose": purpose,
            "expectedKeyVersion": key,
            "expectedVaultVersion": vault,
            "dataBase64": base64.b64encode(blob).decode("ascii"),
        }
        if key_id is not None:
            body["keyId"] = key_id
        if wrap is not None:
            body["wrappedKeyBase64"] = base64.b64encode(wrap).decode("ascii")
        return self.client.put("/api/sync/commit", json=body, headers=self._headers())

    def _put_vault(self, base, key_version, blob, key_id=None):
        body = {"baseVersion": base, "keyVersion": key_version, "dataBase64": base64.b64encode(blob).decode("ascii")}
        if key_id is not None:
            body["keyId"] = key_id
        return self.client.put("/api/sync/vault", json=body, headers=self._headers())

    def _user(self) -> User:
        return db.session.get(User, self.user_id)

    def test_concurrent_establish_allows_one_writer(self):
        barrier = threading.Barrier(2)
        results = []

        def call(blob: bytes):
            barrier.wait(timeout=5)
            with self.app.app_context():
                client = self.app.test_client()
                res = client.put(
                    "/api/sync/commit",
                    json={
                        "purpose": "establish",
                        "expectedKeyVersion": 0,
                        "expectedVaultVersion": 0,
                        "dataBase64": base64.b64encode(blob).decode("ascii"),
                        "keyId": KEY_A,
                    },
                    headers=self._headers(),
                )
                results.append(res.status_code)

        threads = [
            threading.Thread(target=call, args=(b"vault-a",)),
            threading.Thread(target=call, args=(b"vault-b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(sorted(results), [200, 409])
        with self.app.app_context():
            user = self._user()
            self.assertEqual(user.key_version, 1)
            self.assertEqual(user.vault_version, 1)
            self.assertEqual(user.vault_key_id, KEY_A)
            self.assertIsNone(user.wrapped_kpkey)

    def test_establish_retry_is_idempotent(self):
        first = self._commit("establish", 0, 0)
        second = self._commit("establish", 0, 0)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json()["idempotent"])
        self.assertEqual(second.get_json()["vaultKeyId"], KEY_A)
        with self.app.app_context():
            user = self._user()
            self.assertEqual(user.key_version, 1)
            self.assertEqual(user.vault_version, 1)

    def test_wrapped_key_from_old_client_is_never_stored_or_served(self):
        created = self._commit("establish", 0, 0, key_id=None, wrap=b"wrap-from-0.9.1")
        self.assertEqual(created.status_code, 200, created.get_data(as_text=True))
        with self.app.app_context():
            user = self._user()
            self.assertIsNone(user.wrapped_kpkey)
            self.assertIsNone(user.wrapped_key_sha256)
            self.assertIsNone(user.vault_key_id)
        put = self.client.put(
            "/api/sync/wrapped-key",
            json={"dataBase64": base64.b64encode(b"another-wrap").decode("ascii")},
            headers=self._headers(),
        )
        self.assertEqual(put.status_code, 410)
        with self.app.app_context():
            user = self._user()
            user.wrapped_kpkey = b"legacy-wrap-left-by-0.9.1"
            db.session.commit()
        got = self.client.get("/api/sync/wrapped-key", headers=self._headers())
        self.assertEqual(got.status_code, 200)
        self.assertIsNone(got.get_json()["dataBase64"])
        self.assertNotIn("legacy-wrap", got.get_data(as_text=True))
        status = self.client.get("/api/sync/status", headers=self._headers()).get_json()
        self.assertNotIn("hasWrappedKey", status)
        self.assertNotIn("bindingKeyFingerprint", status)

    def test_rotate_conflict_does_not_publish_partial_update(self):
        created = self._commit("establish", 0, 0, blob=b"vault-old")
        self.assertEqual(created.status_code, 200)
        raced = self._commit("rotate", 0, 1, key_id=KEY_B, blob=b"vault-new")
        self.assertEqual(raced.status_code, 409)
        self.assertTrue(raced.get_json()["keyChanged"])
        self.assertEqual(raced.get_json()["vaultKeyId"], KEY_A)
        with self.app.app_context():
            user = self._user()
            self.assertEqual(user.key_version, 1)
            self.assertEqual(user.vault_version, 1)
            self.assertEqual(user.vault_key_id, KEY_A)

    def test_rotate_then_old_key_and_old_client_are_rejected(self):
        self.assertEqual(self._commit("establish", 0, 0).status_code, 200)
        with self.app.app_context():
            user = self._user()
            user.wrapped_kpkey = b"stale-wrap-of-key-a"
            db.session.commit()
        rotated = self._commit("rotate", 1, 1, key_id=KEY_B, blob=b"vault-new")
        self.assertEqual(rotated.status_code, 200)
        self.assertEqual(rotated.get_json()["keyVersion"], 2)
        self.assertEqual(rotated.get_json()["vaultVersion"], 2)
        self.assertEqual(rotated.get_json()["vaultKeyId"], KEY_B)
        stale = self._put_vault(2, 1, b"old-key")
        self.assertEqual(stale.status_code, 409)
        self.assertTrue(stale.get_json()["keyChanged"])
        legacy = self.client.put(
            "/api/sync/vault",
            json={"baseVersion": 2, "dataBase64": base64.b64encode(b"legacy").decode("ascii")},
            headers=self._headers(),
        )
        self.assertEqual(legacy.status_code, 426)
        self.assertTrue(legacy.get_json()["upgradeRequired"])
        with self.app.app_context():
            user = self._user()
            self.assertEqual(user.key_version, 2)
            self.assertEqual(user.vault_version, 2)
            self.assertEqual(user.vault_key_id, KEY_B)
            # 换钥时顺手清掉包着旧密钥的旧版密钥包。
            self.assertIsNone(user.wrapped_kpkey)

    def test_rotate_must_change_the_key(self):
        self.assertEqual(self._commit("establish", 0, 0).status_code, 200)
        same = self._commit("rotate", 1, 1, key_id=KEY_A, blob=b"vault-same-key")
        self.assertEqual(same.status_code, 400)
        self.assertIn("新的加密密钥", same.get_json()["error"])
        with self.app.app_context():
            self.assertEqual(self._user().key_version, 1)

    def test_upload_with_a_different_key_is_rejected_without_writing(self):
        self.assertEqual(self._commit("establish", 0, 0, blob=b"vault-a").status_code, 200)
        wrong = self._put_vault(1, 1, b"encrypted-with-b", key_id=KEY_B)
        self.assertEqual(wrong.status_code, 409)
        body = wrong.get_json()
        self.assertTrue(body["keyChanged"])
        self.assertEqual(body["vaultKeyId"], KEY_A)
        commit = self._commit("vault", 1, 1, key_id=KEY_B, blob=b"encrypted-with-b")
        self.assertEqual(commit.status_code, 409)
        with self.app.app_context():
            from app.vault_storage import read_vault

            user = self._user()
            self.assertEqual(user.vault_version, 1)
            self.assertEqual(read_vault(user), b"vault-a")
        right = self._put_vault(1, 1, b"vault-a2", key_id=KEY_A.lower())
        self.assertEqual(right.status_code, 200, right.get_data(as_text=True))

    def test_legacy_account_learns_key_id_from_first_upload(self):
        with self.app.app_context():
            user = self._user()
            user.key_version = 1
            user.vault_version = 3
            db.session.commit()
        unknown = self._put_vault(3, 1, b"from-0.9.1")
        self.assertEqual(unknown.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(self._user().vault_key_id)
        learned = self._put_vault(4, 1, b"from-1.0.1", key_id=KEY_A)
        self.assertEqual(learned.status_code, 200)
        with self.app.app_context():
            self.assertEqual(self._user().vault_key_id, KEY_A)
        status = self.client.get("/api/sync/status", headers=self._headers()).get_json()
        self.assertEqual(status["vaultKeyId"], KEY_A)

    def test_invalid_key_id_is_rejected(self):
        for bad in ("short", "ZZZZZZZZZZZZ", 123, "83BD38E247B7-extra"):
            res = self._commit("establish", 0, 0, key_id=bad)
            self.assertEqual(res.status_code, 400, bad)
        with self.app.app_context():
            self.assertEqual(self._user().vault_version, 0)

    def test_commit_failure_rolls_back_database_and_file(self):
        with self.app.app_context():
            from app.vault_storage import vault_path

            user = self._user()
            path = vault_path(user)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"previous")
            user.vault_version = 1
            user.vault_sha256 = "previous"
            user.key_version = 1
            user.vault_key_id = KEY_A
            db.session.commit()

        calls = {"n": 0}
        real_commit = db.session.commit

        def fail_second(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise RuntimeError("commit failed")
            return real_commit(*args, **kwargs)

        with patch("app.api.sync.db.session.commit", side_effect=fail_second):
            res = self._commit("rotate", 1, 1, key_id=KEY_B, blob=b"vault-new")
        self.assertGreaterEqual(calls["n"], 2)
        self.assertGreaterEqual(res.status_code, 500)
        body = res.get_data(as_text=True)
        self.assertNotIn("website-password-12", body)
        with self.app.app_context():
            from app.vault_storage import read_vault

            user = self._user()
            self.assertEqual(user.key_version, 1)
            self.assertEqual(user.vault_version, 1)
            self.assertEqual(user.vault_key_id, KEY_A)
            self.assertEqual(read_vault(user), b"previous")

    def test_password_reset_keeps_cloud_vault_and_key_generation(self):
        self.assertEqual(self._commit("establish", 0, 0).status_code, 200)
        with self.app.app_context():
            user = self._user()
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

        with patch("app.api.auth.send_mail"):
            res = self.client.post(
                "/api/auth/reset",
                json={"email": "sync@example.com", "code": code, "newPassword": "another-password-12"},
            )
        self.assertEqual(res.status_code, 200)
        text = res.get_data(as_text=True)
        self.assertNotIn("another-password-12", text)
        with self.app.app_context():
            user = self._user()
            self.assertEqual(user.key_version, 1)
            self.assertEqual(user.vault_version, 1)
            self.assertEqual(user.vault_key_id, KEY_A)
            self.assertEqual(Device.query.filter_by(user_id=user.id, revoked_at=None).count(), 0)


class DeviceBindV101Tests(unittest.TestCase):
    """绑定只要网站账号密码和邮箱验证码。不再有 .kpbind，旧客户端不能新绑定。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)

        class TestConfig(Config):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{(root / 'bind.db').as_posix()}"
            VAULT_STORAGE_DIR = root / "vaults"
            MAIL_DEV_CONSOLE = True
            SMTP_HOST = ""
            SMTP_PASSWORD = ""

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            user = User(email="bind@example.com", password_hash=hash_password("website-password-12"), is_verified=True)
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.tmp.cleanup()

    def _code(self, code="ABCD2345"):
        with self.app.app_context():
            db.session.add(
                EmailToken(
                    user_id=self.user_id,
                    purpose="device_bind",
                    code_hash=hash_token(code),
                    expires_at=utcnow() + timedelta(minutes=15),
                )
            )
            db.session.commit()
        return code

    def _bind(self, version, code="ABCD2345", **extra):
        body = {
            "email": "bind@example.com",
            "password": "website-password-12",
            "code": code,
            "deviceName": "new-pc",
            "platform": "Windows",
            "clientVersion": version,
        }
        body.update(extra)
        return self.client.post("/api/sync/device/bind", json=body)

    def test_bind_needs_only_password_and_email_code(self):
        code = self._code()
        res = self._bind("1.0.1", code)
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertTrue(body["deviceToken"])
        self.assertIsNone(body["vaultKeyId"])
        self.assertNotIn("bindingKeyFingerprint", body)
        self.assertNotIn("hasWrappedKey", body)

    def test_stale_binding_key_field_is_ignored(self):
        code = self._code()
        res = self._bind("1.2.0", code, bindingKey="KPB-anything")
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))

    def test_old_client_cannot_bind_and_keeps_code(self):
        code = self._code()
        for version in ("0.9.1", "1.0.0", "", None, "garbage"):
            res = self._bind(version, code)
            self.assertEqual(res.status_code, 400, version)
            body = res.get_json()
            self.assertTrue(body["upgradeRequired"])
            self.assertIn("1.0.1", body["error"])
            # 客户端只显示不含这些字样的错误文本（SyncApiClient.IsPublicError），否则只剩“请求无效”。
            for hidden in ("password", "secret", "bearer", "kpb-"):
                self.assertNotIn(hidden, body["error"].lower())
        with self.app.app_context():
            self.assertEqual(Device.query.count(), 0)
            token = EmailToken.query.filter_by(user_id=self.user_id, purpose="device_bind").one()
            self.assertIsNone(token.used_at)
            self.assertEqual(token.attempts, 0)
        self.assertEqual(self._bind("1.0.1", code).status_code, 200)

    def test_old_client_gate_does_not_reveal_registration(self):
        unknown = self.client.post(
            "/api/sync/device/bind",
            json={"email": "nobody@example.com", "password": "x", "code": "ABCD2345", "clientVersion": "0.9.1"},
        )
        known = self._bind("0.9.1")
        self.assertEqual(unknown.status_code, known.status_code)
        self.assertEqual(unknown.get_json(), known.get_json())

    def test_verify_email_no_longer_issues_binding_file(self):
        with self.app.app_context():
            user = User(email="new@example.com", password_hash=hash_password("website-password-12"), is_verified=False)
            db.session.add(user)
            db.session.flush()
            db.session.add(
                EmailToken(
                    user_id=user.id,
                    purpose="verify",
                    code_hash=hash_token("ABCD2345"),
                    expires_at=utcnow() + timedelta(minutes=60),
                )
            )
            db.session.commit()
        res = self.client.post("/api/auth/verify-email", json={"email": "new@example.com", "code": "ABCD2345"})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(set(body), {"ok", "token"})
        self.assertNotIn("kpbind", res.get_data(as_text=True))
        with self.app.app_context():
            user = User.query.filter_by(email="new@example.com").one()
            self.assertTrue(user.is_verified)
            self.assertIsNone(user.binding_key_hash)
        again = self.client.post("/api/auth/verify-email", json={"email": "new@example.com", "code": "ABCD2345"})
        self.assertEqual(again.status_code, 400)

    def test_binding_key_regeneration_is_gone(self):
        with self.app.app_context():
            web = issue_web_token(db.session.get(User, self.user_id))
        headers = {"Authorization": f"Bearer {web}"}
        self.assertEqual(self.client.post("/api/me/binding-key/regenerate", json={}, headers=headers).status_code, 404)
        purpose = self.client.post("/api/me/request-code", json={"purpose": "regen_binding_key"}, headers=headers)
        self.assertEqual(purpose.status_code, 400)
        me = self.client.get("/api/me", headers=headers).get_json()
        self.assertIn("vaultKeyId", me)
        self.assertNotIn("bindingKeyFingerprint", me)
        self.assertNotIn("hasWrappedKey", me)

    def test_purge_clears_legacy_wrap_and_binding_key(self):
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            user.wrapped_kpkey = b"legacy-wrap"
            user.wrapped_key_sha256 = "abc"
            user.wrapped_kpkey_updated_at = utcnow()
            user.binding_key_hash = "hash"
            user.binding_key_fingerprint = "fp"
            user.binding_key_created_at = utcnow()
            user.vault_version = 2
            user.key_version = 1
            user.vault_key_id = KEY_A
            other = User(email="clean@example.com", password_hash=hash_password("website-password-12"), is_verified=True)
            db.session.add(other)
            db.session.commit()
            self.assertEqual(purge_legacy_keys(), 1)
            self.assertEqual(purge_legacy_keys(), 0)
            user = db.session.get(User, self.user_id)
            for column in (
                "wrapped_kpkey",
                "wrapped_key_sha256",
                "wrapped_kpkey_updated_at",
                "binding_key_hash",
                "binding_key_fingerprint",
                "binding_key_created_at",
            ):
                self.assertIsNone(getattr(user, column), column)
            self.assertEqual((user.vault_version, user.key_version, user.vault_key_id), (2, 1, KEY_A))
        result = self.app.test_cli_runner().invoke(args=["purge-legacy-keys"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("0 个账号", result.output)


if __name__ == "__main__":
    unittest.main()
