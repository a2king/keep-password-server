from __future__ import annotations

import base64
import hashlib
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Device, DevicePairing, User, utcnow
from app.security import hash_password, hash_token, issue_device_token


def pub() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def commit(key: str) -> str:
    return hashlib.sha256(b"keep-password/pair-commit/v1" + base64.b64decode(key)).hexdigest()


class DevicePairingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)

        class TestConfig(Config):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{(root / 'pair.db').as_posix()}"
            VAULT_STORAGE_DIR = root / "vaults"
            MAIL_DEV_CONSOLE = True
            SMTP_HOST = ""
            SMTP_PASSWORD = ""

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            self.new = self._device("me@example.com", "new-pc")
            self.old = self._device("me@example.com", "old-pc")
            self.third = self._device("me@example.com", "laptop")
            self.stranger = self._device("other@example.com", "theirs")

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.tmp.cleanup()

    def _device(self, email: str, name: str) -> dict:
        user = User.query.filter_by(email=email).first()
        if user is None:
            user = User(email=email, password_hash=hash_password("website-password-12"), is_verified=True)
            db.session.add(user)
            db.session.flush()
        device = Device(user_id=user.id, name=name, platform="Windows", client_version="1.0.1", token_hash="pending-" + name)
        db.session.add(device)
        db.session.flush()
        token = issue_device_token(user, device)
        device.token_hash = hash_token(token)
        db.session.commit()
        return {"Authorization": f"Bearer {token}"}

    def _start(self):
        key = pub()
        res = self.client.post("/api/sync/pairing", json={"commitment": commit(key)}, headers=self.new)
        self.assertEqual(res.status_code, 201, res.get_data(as_text=True))
        return res.get_json()["pairingId"], key

    def test_full_flow_server_only_relays(self):
        pairing, new_key = self._start()
        pending = self.client.get("/api/sync/pairing/pending", headers=self.old).get_json()["requests"]
        self.assertEqual([p["pairingId"] for p in pending], [pairing])
        self.assertEqual(pending[0]["requesterDeviceName"], "new-pc")
        self.assertIsNone(pending[0]["requesterPublicKey"])
        # 请求方自己看不到“待处理”，别的账号也看不到。
        self.assertEqual(self.client.get("/api/sync/pairing/pending", headers=self.new).get_json()["requests"], [])
        self.assertEqual(self.client.get("/api/sync/pairing/pending", headers=self.stranger).get_json()["requests"], [])

        old_key = pub()
        offered = self.client.post(f"/api/sync/pairing/{pairing}/offer", json={"publicKey": old_key}, headers=self.old)
        self.assertEqual(offered.status_code, 200)
        # 第二台设备再响应会冲突，也不再在它的待处理里出现。
        self.assertEqual(self.client.post(f"/api/sync/pairing/{pairing}/offer", json={"publicKey": pub()}, headers=self.third).status_code, 409)
        self.assertEqual(self.client.get("/api/sync/pairing/pending", headers=self.third).get_json()["requests"], [])

        state = self.client.get(f"/api/sync/pairing/{pairing}", headers=self.new).get_json()
        self.assertEqual((state["status"], state["approverPublicKey"], state["approverDeviceName"]), ("offered", old_key, "old-pc"))

        # 公开的公钥必须与承诺一致。
        self.assertEqual(self.client.post(f"/api/sync/pairing/{pairing}/reveal", json={"publicKey": pub()}, headers=self.new).status_code, 400)
        revealed = self.client.post(f"/api/sync/pairing/{pairing}/reveal", json={"publicKey": new_key}, headers=self.new)
        self.assertEqual(revealed.status_code, 200)
        self.assertEqual(self.client.post(f"/api/sync/pairing/{pairing}/reveal", json={"publicKey": new_key}, headers=self.new).status_code, 200)

        # 只有响应的那台设备能批准。
        self.assertEqual(self.client.post(f"/api/sync/pairing/{pairing}/approve", json={"envelope": "x"}, headers=self.third).status_code, 404)
        self.assertEqual(self.client.post(f"/api/sync/pairing/{pairing}/approve", json={"envelope": "opaque-envelope"}, headers=self.old).status_code, 200)

        # 信封只给请求方。
        self.assertNotIn("envelope", self.client.get(f"/api/sync/pairing/{pairing}", headers=self.old).get_json())
        got = self.client.get(f"/api/sync/pairing/{pairing}", headers=self.new).get_json()
        self.assertEqual((got["status"], got["envelope"]), ("approved", "opaque-envelope"))

        self.assertEqual(self.client.post(f"/api/sync/pairing/{pairing}/complete", headers=self.new).status_code, 200)
        with self.app.app_context():
            row = db.session.get(DevicePairing, pairing)
            self.assertEqual(row.status, "completed")
            self.assertIsNone(row.envelope)
            self.assertIsNone(row.requester_public_key)
            self.assertIsNone(row.approver_public_key)

    def test_other_account_cannot_touch_request(self):
        pairing, _ = self._start()
        for path in ("", "/offer", "/reject", "/approve", "/complete"):
            method = self.client.get if path == "" else self.client.post
            res = method(f"/api/sync/pairing/{pairing}{path}", json={"publicKey": pub(), "envelope": "x"}, headers=self.stranger)
            self.assertEqual(res.status_code, 404, path)

    def test_reject_by_another_device_and_cancel_by_requester(self):
        pairing, _ = self._start()
        res = self.client.post(f"/api/sync/pairing/{pairing}/reject", headers=self.third)
        self.assertEqual(res.get_json()["status"], "rejected")
        self.assertEqual(self.client.get(f"/api/sync/pairing/{pairing}", headers=self.new).get_json()["status"], "rejected")
        self.assertEqual(self.client.post(f"/api/sync/pairing/{pairing}/offer", json={"publicKey": pub()}, headers=self.old).status_code, 409)

        second, _ = self._start()
        self.assertEqual(self.client.post(f"/api/sync/pairing/{second}/reject", headers=self.new).get_json()["status"], "cancelled")

    def test_new_request_cancels_previous_one_from_same_device(self):
        first, _ = self._start()
        second, _ = self._start()
        with self.app.app_context():
            self.assertEqual(db.session.get(DevicePairing, first).status, "cancelled")
            self.assertEqual(db.session.get(DevicePairing, second).status, "requested")

    def test_expired_request_is_hidden_and_frozen(self):
        pairing, _ = self._start()
        with self.app.app_context():
            row = db.session.get(DevicePairing, pairing)
            row.expires_at = utcnow() - timedelta(seconds=1)
            db.session.commit()
        self.assertEqual(self.client.get("/api/sync/pairing/pending", headers=self.old).get_json()["requests"], [])
        self.assertEqual(self.client.post(f"/api/sync/pairing/{pairing}/offer", json={"publicKey": pub()}, headers=self.old).status_code, 404)
        self.assertEqual(self.client.get(f"/api/sync/pairing/{pairing}", headers=self.new).get_json()["status"], "expired")

    def test_input_validation_and_rate_limit(self):
        self.assertEqual(self.client.post("/api/sync/pairing", json={"commitment": "zz"}, headers=self.new).status_code, 400)
        pairing, _ = self._start()
        for bad in ("short", base64.b64encode(b"x" * 31).decode(), 123):
            self.assertEqual(self.client.post(f"/api/sync/pairing/{pairing}/offer", json={"publicKey": bad}, headers=self.old).status_code, 400)
        self.assertEqual(self.client.get("/api/sync/pairing/../vault", headers=self.new).status_code, 404)
        with patch.dict(self.app.config, {"PAIRING_PER_10_MIN": 3}):
            codes = [self.client.post("/api/sync/pairing", json={"commitment": commit(pub())}, headers=self.new).status_code for _ in range(3)]
        self.assertEqual(codes, [201, 201, 429])

    def test_requires_device_token(self):
        self.assertEqual(self.client.post("/api/sync/pairing", json={"commitment": commit(pub())}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
