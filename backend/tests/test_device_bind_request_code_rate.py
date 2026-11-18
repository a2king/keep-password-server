from __future__ import annotations

import hashlib
import multiprocessing
import os
import tempfile
import threading
import traceback
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import inspect

from app import create_app
from app.config import Config
from app.device_bind_rate import RATE_LIMIT_ERROR, hash_normalized_email
from app.extensions import db
from app.mail import MailError
from app.models import DeviceBindCodeRequest, EmailToken, User
from app.security import hash_password, hash_token
from app.tokens import consume_email_code


def _independent_sqlite_request(payload: dict, ready, start, result_queue) -> None:
    """独立进程、独立 SQLAlchemy 引擎访问同一 SQLite 文件，模拟 gunicorn worker。"""
    try:
        db_path = payload["db_path"]
        vault_dir = payload["vault_dir"]
        email = payload["email"]
        ip = payload["ip"]

        class WorkerConfig(Config):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{Path(db_path).as_posix()}"
            SQLALCHEMY_ENGINE_OPTIONS = {
                "connect_args": {"check_same_thread": False, "timeout": 30},
            }
            VAULT_STORAGE_DIR = Path(vault_dir)
            MAIL_DEV_CONSOLE = True
            SMTP_HOST = ""
            SMTP_PASSWORD = ""
            TRUST_PROXY = False

        app = create_app(WorkerConfig, init_db=False)
        ready.set()
        if not start.wait(timeout=15):
            result_queue.put((-1, {"error": "start timeout"}))
            return
        with app.test_client() as client:
            res = client.post(
                "/api/sync/device/request-code",
                json={"email": email},
                environ_base={"REMOTE_ADDR": ip},
            )
            result_queue.put((res.status_code, res.get_json()))
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
    except Exception as exc:
        result_queue.put((-1, {"error": f"{exc}\n{traceback.format_exc()}"}))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


class DeviceBindRequestCodeRateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)

        class TestConfig(Config):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{(root / 'rate.db').as_posix()}"
            SQLALCHEMY_ENGINE_OPTIONS = {
                "connect_args": {"check_same_thread": False, "timeout": 30},
            }
            VAULT_STORAGE_DIR = root / "vaults"
            MAIL_DEV_CONSOLE = True
            SMTP_HOST = ""
            SMTP_PASSWORD = ""
            TRUST_PROXY = False

        self.db_path = root / "rate.db"
        self.vault_dir = root / "vaults"
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.mail_patcher = patch("app.tokens.send_mail")
        self.send_mail = self.mail_patcher.start()

    def tearDown(self):
        try:
            self.mail_patcher.stop()
        except RuntimeError:
            pass
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.tmp.cleanup()

    def _post(self, email: str, *, ip: str | None = None, xff: str | None = None):
        kwargs = {"json": {"email": email}}
        if xff is not None:
            kwargs["headers"] = {"X-Forwarded-For": xff}
        if ip is not None:
            kwargs["environ_base"] = {"REMOTE_ADDR": ip}
        return self.client.post("/api/sync/device/request-code", **kwargs)

    def _seed_user(
        self,
        email: str,
        *,
        verified: bool = True,
        disabled: bool = False,
    ) -> User:
        with self.app.app_context():
            user = User(
                email=email,
                password_hash=hash_password("website-password-12"),
                is_verified=verified,
                is_disabled=disabled,
            )
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id
            return user

    def test_second_request_within_60s_is_429(self):
        self._seed_user("owner@example.com")
        first = self._post("owner@example.com")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json(), {"ok": True})
        self.assertEqual(self.send_mail.call_count, 1)
        second = self._post("owner@example.com")
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.get_json(), {"error": RATE_LIMIT_ERROR})
        self.assertEqual(list(second.get_json().keys()), ["error"])
        self.assertEqual(self.send_mail.call_count, 1)

    def test_allowed_after_exactly_60s(self):
        clock = Clock(datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc))
        self._seed_user("owner@example.com")
        with patch("app.device_bind_rate.utcnow", clock):
            self.assertEqual(self._post("owner@example.com").status_code, 200)
            clock.advance(seconds=59)
            blocked = self._post("owner@example.com")
            self.assertEqual(blocked.status_code, 429)
            clock.advance(seconds=1)
            allowed = self._post("owner@example.com")
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(allowed.get_json(), {"ok": True})
        self.assertEqual(self.send_mail.call_count, 2)

    def test_unknown_email_uses_same_limit_and_json(self):
        first = self._post("nobody@example.com")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json(), {"ok": True})
        self.send_mail.assert_not_called()
        second = self._post("nobody@example.com")
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.get_json(), {"error": RATE_LIMIT_ERROR})
        self.send_mail.assert_not_called()
        with self.app.app_context():
            self.assertIsNone(User.query.filter_by(email="nobody@example.com").first())
            rows = DeviceBindCodeRequest.query.all()
            self.assertEqual(len(rows), 2)
            hashes = {row.email_hash for row in rows}
            self.assertEqual(hashes, {hash_normalized_email("nobody@example.com"), None})

    def test_rate_limited_request_does_not_invalidate_previous_code(self):
        self._seed_user("owner@example.com")
        first = self._post("owner@example.com")
        self.assertEqual(first.status_code, 200)
        known = "ABCD2345"
        with self.app.app_context():
            token = (
                EmailToken.query.filter_by(user_id=self.user_id, purpose="device_bind", used_at=None)
                .order_by(EmailToken.id.desc())
                .one()
            )
            token_id = token.id
            token.code_hash = hash_token(known)
            db.session.commit()
        second = self._post("owner@example.com")
        self.assertEqual(second.status_code, 429)
        with self.app.app_context():
            token = db.session.get(EmailToken, token_id)
            self.assertIsNone(token.used_at)
            user = db.session.get(User, self.user_id)
            self.assertTrue(consume_email_code(user, "device_bind", known))

    def test_hourly_email_cap_is_10(self):
        clock = Clock(datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc))
        self._seed_user("owner@example.com")
        with patch("app.device_bind_rate.utcnow", clock):
            for _ in range(10):
                res = self._post("owner@example.com")
                self.assertEqual(res.status_code, 200, res.get_json())
                clock.advance(seconds=61)
            blocked = self._post("owner@example.com")
            self.assertEqual(blocked.status_code, 429)
            clock.now = datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)
            allowed = self._post("owner@example.com")
            self.assertEqual(allowed.status_code, 200)
        self.assertEqual(self.send_mail.call_count, 11)

    def test_ip_cap_is_30_requests_including_rejects(self):
        for i in range(30):
            res = self._post(f"ip-user-{i}@example.com", ip="203.0.113.10")
            self.assertEqual(res.status_code, 200, res.get_json())
        blocked = self._post("ip-user-30@example.com", ip="203.0.113.10")
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.get_json(), {"error": RATE_LIMIT_ERROR})
        other_ip = self._post("ip-user-30@example.com", ip="203.0.113.11")
        self.assertEqual(other_ip.status_code, 200)
        with self.app.app_context():
            counted = DeviceBindCodeRequest.query.filter_by(ip="203.0.113.10").count()
            self.assertEqual(counted, 31)

    def test_mixed_email_statuses_share_ip_and_same_429(self):
        self._seed_user("verified@example.com", verified=True)
        self._seed_user("pending@example.com", verified=False)
        self._seed_user("disabled@example.com", verified=True, disabled=True)
        statuses = []
        for email in (
            "verified@example.com",
            "pending@example.com",
            "disabled@example.com",
            "missing@example.com",
        ):
            res = self._post(email, ip="198.51.100.8")
            statuses.append((email, res.status_code, res.get_json()))
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.get_json(), {"ok": True})
        self.assertEqual(self.send_mail.call_count, 1)
        for email in (
            "verified@example.com",
            "pending@example.com",
            "disabled@example.com",
            "missing@example.com",
        ):
            res = self._post(email, ip="198.51.100.8")
            self.assertEqual(res.status_code, 429, email)
            self.assertEqual(res.get_json(), {"error": RATE_LIMIT_ERROR})
        self.assertEqual(self.send_mail.call_count, 1)
        with self.app.app_context():
            ip_rows = DeviceBindCodeRequest.query.filter_by(ip="198.51.100.8").count()
            self.assertEqual(ip_rows, 8)

    def test_normalized_email_shares_hash_and_never_stores_plaintext(self):
        first = self._post("User@Example.COM")
        self.assertEqual(first.status_code, 200)
        second = self._post("user@example.com")
        self.assertEqual(second.status_code, 429)
        expected = hash_normalized_email("user@example.com")
        self.assertEqual(expected, _sha256("user@example.com"))
        with self.app.app_context():
            columns = {col["name"] for col in inspect(db.engine).get_columns("device_bind_code_requests")}
            self.assertEqual(columns, {"id", "email_hash", "ip", "created_at"})
            self.assertNotIn("email", columns)
            for row in DeviceBindCodeRequest.query.all():
                blob = "".join(str(value) for value in (row.id, row.email_hash, row.ip, row.created_at))
                self.assertNotIn("User@Example.COM", blob)
                self.assertNotIn("user@example.com", blob)
            allowed = DeviceBindCodeRequest.query.filter(DeviceBindCodeRequest.email_hash.isnot(None)).one()
            self.assertEqual(allowed.email_hash, expected)
            self.assertEqual(len(allowed.email_hash), 64)

    def test_client_ip_honors_trusted_proxy_only(self):
        with self.app.app_context():
            for i in range(30):
                db.session.add(
                    DeviceBindCodeRequest(
                        email_hash=None,
                        ip="127.0.0.1",
                        created_at=datetime.now(timezone.utc),
                    )
                )
            db.session.commit()
        spoofed = self._post("proxy-a@example.com", xff="198.51.100.20, 10.0.0.1")
        self.assertEqual(spoofed.status_code, 429)
        self.app.config["TRUST_PROXY"] = True
        trusted = self._post("proxy-a@example.com", xff="198.51.100.20, 10.0.0.1")
        self.assertEqual(trusted.status_code, 200)
        with self.app.app_context():
            trusted_rows = DeviceBindCodeRequest.query.filter_by(ip="198.51.100.20").all()
            self.assertEqual(len(trusted_rows), 1)
            self.assertEqual(trusted_rows[0].email_hash, hash_normalized_email("proxy-a@example.com"))
            self.assertFalse(any(row.ip == "10.0.0.1" for row in DeviceBindCodeRequest.query.all()))

    def test_cleans_records_older_than_24h(self):
        clock = Clock(datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc))
        digest = hash_normalized_email("old@example.com")
        with self.app.app_context():
            db.session.add_all(
                [
                    DeviceBindCodeRequest(
                        email_hash=digest,
                        ip="203.0.113.40",
                        created_at=clock.now - timedelta(hours=25),
                    ),
                    DeviceBindCodeRequest(
                        email_hash=hash_normalized_email("keep@example.com"),
                        ip="203.0.113.40",
                        created_at=clock.now - timedelta(hours=2),
                    ),
                ]
            )
            db.session.commit()
        with patch("app.device_bind_rate.utcnow", clock):
            res = self._post("fresh@example.com", ip="203.0.113.41")
        self.assertEqual(res.status_code, 200)
        with self.app.app_context():
            remaining = {(row.email_hash, row.ip) for row in DeviceBindCodeRequest.query.all()}
            self.assertNotIn((digest, "203.0.113.40"), remaining)
            self.assertIn((hash_normalized_email("keep@example.com"), "203.0.113.40"), remaining)
            self.assertIn((hash_normalized_email("fresh@example.com"), "203.0.113.41"), remaining)

    def test_concurrent_requests_do_not_exceed_quota_and_keep_previous_code(self):
        self._seed_user("owner@example.com")
        self.assertEqual(self._post("owner@example.com").status_code, 200)
        known = "ABCD2345"
        with self.app.app_context():
            token = (
                EmailToken.query.filter_by(user_id=self.user_id, purpose="device_bind", used_at=None)
                .order_by(EmailToken.id.desc())
                .one()
            )
            token_id = token.id
            token.code_hash = hash_token(known)
            db.session.commit()
        barrier = threading.Barrier(4)
        results = []

        def call():
            barrier.wait(timeout=5)
            with self.app.app_context():
                client = self.app.test_client()
                res = client.post("/api/sync/device/request-code", json={"email": "owner@example.com"})
                results.append((res.status_code, res.get_json()))

        threads = [threading.Thread(target=call) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertEqual(len(results), 4)
        self.assertEqual({status for status, _ in results}, {429})
        for _, body in results:
            self.assertEqual(body, {"error": RATE_LIMIT_ERROR})
        self.assertEqual(self.send_mail.call_count, 1)
        with self.app.app_context():
            token = db.session.get(EmailToken, token_id)
            self.assertIsNone(token.used_at)
            user = db.session.get(User, self.user_id)
            self.assertTrue(consume_email_code(user, "device_bind", known))

    def _run_independent_sqlite_workers(self, email: str, n: int, ip: str) -> list[tuple[int, object]]:
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        ctx = multiprocessing.get_context("spawn")
        ready_events = [ctx.Event() for _ in range(n)]
        start = ctx.Event()
        result_queue = ctx.Queue()
        payload = {
            "db_path": str(self.db_path),
            "vault_dir": str(self.vault_dir / f"mp-{os.getpid()}"),
            "email": email,
            "ip": ip,
        }
        procs = [
            ctx.Process(
                target=_independent_sqlite_request,
                args=(payload, ready_events[i], start, result_queue),
            )
            for i in range(n)
        ]
        for proc in procs:
            proc.start()
        for event in ready_events:
            self.assertTrue(event.wait(timeout=20), "worker failed to become ready")
        start.set()
        for proc in procs:
            proc.join(timeout=40)
            self.assertFalse(proc.is_alive(), "worker hung")
        results = []
        while not result_queue.empty():
            results.append(result_queue.get())
        self.assertEqual(len(results), n, results)
        return results

    def test_concurrent_first_wave_issues_only_one_code(self):
        self._seed_user("burst@example.com")
        barrier = threading.Barrier(5)
        results = []

        def call():
            barrier.wait(timeout=5)
            with self.app.app_context():
                client = self.app.test_client()
                res = client.post("/api/sync/device/request-code", json={"email": "burst@example.com"})
                results.append(res.status_code)

        threads = [threading.Thread(target=call) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertEqual(len(results), 5)
        self.assertEqual(sorted(results), [200, 429, 429, 429, 429])
        self.assertEqual(self.send_mail.call_count, 1)
        with self.app.app_context():
            tokens = EmailToken.query.filter_by(user_id=self.user_id, purpose="device_bind").all()
            self.assertEqual(len(tokens), 1)
            allowed = DeviceBindCodeRequest.query.filter(
                DeviceBindCodeRequest.email_hash == hash_normalized_email("burst@example.com")
            ).count()
            self.assertEqual(allowed, 1)

    def test_multiprocess_independent_connections_issue_only_one_code(self):
        email = "mp-burst@example.com"
        self._seed_user(email)
        results = self._run_independent_sqlite_workers(email, 5, "203.0.113.80")
        statuses = sorted(status for status, _ in results)
        self.assertEqual(statuses, [200, 429, 429, 429, 429], results)
        for status, body in results:
            if status == 200:
                self.assertEqual(body, {"ok": True})
            else:
                self.assertEqual(body, {"error": RATE_LIMIT_ERROR})
        with self.app.app_context():
            tokens = EmailToken.query.filter_by(user_id=self.user_id, purpose="device_bind").all()
            self.assertEqual(len(tokens), 1)
            allowed = DeviceBindCodeRequest.query.filter(
                DeviceBindCodeRequest.email_hash == hash_normalized_email(email)
            ).count()
            self.assertEqual(allowed, 1)
            self.assertEqual(DeviceBindCodeRequest.query.filter_by(ip="203.0.113.80").count(), 5)

    def test_multiprocess_rejects_keep_previous_code(self):
        email = "mp-keep@example.com"
        self._seed_user(email)
        self.assertEqual(self._post(email).status_code, 200)
        known = "ABCD2345"
        with self.app.app_context():
            token = (
                EmailToken.query.filter_by(user_id=self.user_id, purpose="device_bind", used_at=None)
                .order_by(EmailToken.id.desc())
                .one()
            )
            token_id = token.id
            token.code_hash = hash_token(known)
            db.session.commit()
        results = self._run_independent_sqlite_workers(email, 4, "203.0.113.81")
        self.assertEqual({status for status, _ in results}, {429}, results)
        for _, body in results:
            self.assertEqual(body, {"error": RATE_LIMIT_ERROR})
        with self.app.app_context():
            token = db.session.get(EmailToken, token_id)
            self.assertIsNone(token.used_at)
            user = db.session.get(User, self.user_id)
            self.assertTrue(consume_email_code(user, "device_bind", known))
            tokens = EmailToken.query.filter_by(user_id=self.user_id, purpose="device_bind").all()
            self.assertEqual(len(tokens), 1)

    def test_rejection_count_survives_later_session_rollback(self):
        first = self._post("keep-rollback@example.com")
        self.assertEqual(first.status_code, 200)
        second = self._post("keep-rollback@example.com")
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.get_json(), {"error": RATE_LIMIT_ERROR})
        with self.app.app_context():
            before = DeviceBindCodeRequest.query.count()
            rejected = DeviceBindCodeRequest.query.filter(DeviceBindCodeRequest.email_hash.is_(None)).count()
            self.assertEqual(before, 2)
            self.assertEqual(rejected, 1)
            db.session.add(
                DeviceBindCodeRequest(
                    email_hash="a" * 64,
                    ip="192.0.2.9",
                )
            )
            db.session.flush()
            db.session.rollback()
            self.assertEqual(DeviceBindCodeRequest.query.count(), before)
            self.assertEqual(
                DeviceBindCodeRequest.query.filter(DeviceBindCodeRequest.email_hash.is_(None)).count(),
                1,
            )
        third = self._post("keep-rollback@example.com")
        self.assertEqual(third.status_code, 429)
        self.assertEqual(self.send_mail.call_count, 0)

    def test_quota_commit_rollback_does_not_issue_code(self):
        self._seed_user("roll@example.com")
        with patch("app.device_bind_rate.db.session.commit", side_effect=RuntimeError("quota commit failed")):
            try:
                res = self._post("roll@example.com")
            except RuntimeError:
                pass
            else:
                self.assertEqual(res.status_code, 500)
        self.assertEqual(self.send_mail.call_count, 0)
        with self.app.app_context():
            db.session.rollback()
            db.session.remove()
            self.assertEqual(DeviceBindCodeRequest.query.count(), 0)
            self.assertEqual(EmailToken.query.count(), 0)
        retry = self._post("roll@example.com")
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.get_json(), {"ok": True})
        self.assertEqual(self.send_mail.call_count, 1)
        with self.app.app_context():
            self.assertEqual(DeviceBindCodeRequest.query.count(), 1)
            self.assertEqual(EmailToken.query.filter_by(purpose="device_bind").count(), 1)

    def test_smtp_failure_still_503_and_consumes_quota(self):
        self.mail_patcher.stop()
        self._seed_user("mailfail@example.com")
        with patch(
            "app.tokens.send_mail",
            side_effect=MailError("邮件发送失败：无法连接 SMTP 服务器。"),
        ):
            res = self._post("mailfail@example.com")
        self.assertEqual(res.status_code, 503)
        self.assertIn("邮件发送失败", res.get_json()["error"])
        with patch("app.tokens.send_mail") as send_mail:
            blocked = self._post("mailfail@example.com")
        self.assertEqual(blocked.status_code, 429)
        send_mail.assert_not_called()

    def test_invalid_email_is_400_and_not_counted(self):
        res = self._post("not-an-email")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json(), {"error": "邮箱格式不正确"})
        with self.app.app_context():
            self.assertEqual(DeviceBindCodeRequest.query.count(), 0)

    def test_health_and_bind_contract_untouched(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.get_json(), {"ok": True, "service": "keep-password-server"})
        self._seed_user("bind@example.com")
        self.assertEqual(self._post("bind@example.com").status_code, 200)
        code = "ABCD2345"
        with self.app.app_context():
            token = (
                EmailToken.query.filter_by(user_id=self.user_id, purpose="device_bind", used_at=None)
                .order_by(EmailToken.id.desc())
                .one()
            )
            token.code_hash = hash_token(code)
            db.session.commit()
        bind = self.client.post(
            "/api/sync/device/bind",
            json={
                "email": "bind@example.com",
                "password": "website-password-12",
                "code": code,
                "deviceName": "test-pc",
                "platform": "linux",
                "clientVersion": "1.0.1",
            },
        )
        self.assertEqual(bind.status_code, 200, bind.get_data(as_text=True))
        body = bind.get_json()
        self.assertEqual(
            set(body),
            {
                "deviceToken",
                "deviceId",
                "vaultVersion",
                "vaultKeyId",
                "hasVault",
                "keyVersion",
                "serverTime",
            },
        )
        self.assertNotIn("password", bind.get_data(as_text=True).lower())
        with self.app.app_context():
            tables = inspect(db.engine).get_table_names()
        self.assertIn("device_bind_code_requests", tables)


if __name__ == "__main__":
    unittest.main()
