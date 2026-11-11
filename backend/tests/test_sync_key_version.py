from __future__ import annotations

import base64
import tempfile
import threading
import unittest
from pathlib import Path

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Device, EmailToken, User, utcnow
from app.security import hash_password, hash_token, issue_device_token
from datetime import timedelta


class SyncKeyVersionTests(unittest.TestCase):
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
                client_version="0.9.1",
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

    def _commit(self, purpose, key, vault, wrap=b"wrap-v1", blob=b"vault-v1"):
        body = {
            "purpose": purpose,
            "expectedKeyVersion": key,
            "expectedVaultVersion": vault,
            "dataBase64": base64.b64encode(blob).decode("ascii"),
        }
        if wrap is not None:
            body["wrappedKeyBase64"] = base64.b64encode(wrap).decode("ascii")
        return self.client.put("/api/sync/commit", json=body, headers=self._headers())

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
                        "wrappedKeyBase64": base64.b64encode(blob).decode("ascii"),
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
            self.assertIsNotNone(user.wrapped_kpkey)

    def test_establish_retry_is_idempotent(self):
        first = self._commit("establish", 0, 0)
        second = self._commit("establish", 0, 0)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json()["idempotent"])
        with self.app.app_context():
            user = self._user()
            self.assertEqual(user.key_version, 1)
            self.assertEqual(user.vault_version, 1)

    def test_rotate_conflict_does_not_publish_partial_update(self):
        created = self._commit("establish", 0, 0, wrap=b"wrap-old", blob=b"vault-old")
        self.assertEqual(created.status_code, 200)
        raced = self._commit("rotate", 0, 1, wrap=b"wrap-new", blob=b"vault-new")
        self.assertEqual(raced.status_code, 409)
        self.assertTrue(raced.get_json()["keyChanged"])
        with self.app.app_context():
            user = self._user()
            self.assertEqual(user.key_version, 1)
            self.assertEqual(user.vault_version, 1)
            self.assertEqual(user.wrapped_kpkey, b"wrap-old")

    def test_rotate_then_old_key_and_old_client_are_rejected(self):
        self.assertEqual(self._commit("establish", 0, 0).status_code, 200)
        rotated = self._commit("rotate", 1, 1, wrap=b"wrap-new", blob=b"vault-new")
        self.assertEqual(rotated.status_code, 200)
        self.assertEqual(rotated.get_json()["keyVersion"], 2)
        self.assertEqual(rotated.get_json()["vaultVersion"], 2)
        stale = self.client.put(
            "/api/sync/vault",
            json={"baseVersion": 2, "keyVersion": 1, "dataBase64": base64.b64encode(b"old-key").decode("ascii")},
            headers=self._headers(),
        )
        self.assertEqual(stale.status_code, 409)
        self.assertTrue(stale.get_json()["keyChanged"])
        legacy = self.client.put(
            "/api/sync/vault",
            json={"baseVersion": 2, "dataBase64": base64.b64encode(b"legacy").decode("ascii")},
            headers=self._headers(),
        )
        self.assertEqual(legacy.status_code, 426)
        self.assertTrue(legacy.get_json()["upgradeRequired"])
        overwrite = self.client.put(
            "/api/sync/wrapped-key",
            json={"dataBase64": base64.b64encode(b"another-wrap").decode("ascii")},
            headers=self._headers(),
        )
        self.assertEqual(overwrite.status_code, 409)
        with self.app.app_context():
            user = self._user()
            self.assertEqual(user.key_version, 2)
            self.assertEqual(user.vault_version, 2)
            self.assertEqual(user.wrapped_kpkey, b"wrap-new")

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
            user.wrapped_kpkey = b"wrap-old"
            user.wrapped_key_sha256 = "old"
            db.session.commit()

        from unittest.mock import patch

        calls = {"n": 0}
        real_commit = db.session.commit

        def fail_second(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise RuntimeError("commit failed")
            return real_commit(*args, **kwargs)

        with patch("app.api.sync.db.session.commit", side_effect=fail_second):
            res = self._commit("rotate", 1, 1, wrap=b"wrap-new", blob=b"vault-new")
        self.assertGreaterEqual(calls["n"], 2)
        self.assertGreaterEqual(res.status_code, 500)
        body = res.get_data(as_text=True)
        self.assertNotIn("website-password-12", body)
        with self.app.app_context():
            from app.vault_storage import read_vault

            user = self._user()
            self.assertEqual(user.key_version, 1)
            self.assertEqual(user.vault_version, 1)
            self.assertEqual(user.wrapped_kpkey, b"wrap-old")
            self.assertEqual(read_vault(user), b"previous")

    def test_password_reset_does_not_delete_wrapped_key(self):
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
        from unittest.mock import patch

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
            self.assertIsNotNone(user.wrapped_kpkey)
            self.assertEqual(Device.query.filter_by(user_id=user.id, revoked_at=None).count(), 0)


if __name__ == "__main__":
    unittest.main()
