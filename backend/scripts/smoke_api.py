"""本地冒烟：注册 → 验证 → 登录 → 设备绑定 → 上传/下载保险库。"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

# 允许直接 `python scripts/smoke_api.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.extensions import db
from app.models import EmailToken, User
from app.security import hash_token


def main() -> int:
    app = create_app()
    app.config["MAIL_DEV_CONSOLE"] = True
    client = app.test_client()

    email = "smoke@example.com"
    password = "long-password-12"

    with app.app_context():
        User.query.filter_by(email=email).delete()
        db.session.commit()

    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.data

    with app.app_context():
        user = User.query.filter_by(email=email).one()
        token = EmailToken.query.filter_by(user_id=user.id, purpose="verify").order_by(EmailToken.id.desc()).first()
        # 找回明文：重新发一次并解析不现实；直接用已知方式——从 hash 反推不可行。
        # 测试里直接写一个已知验证码。
        token.code_hash = hash_token("123456")
        db.session.commit()

    r = client.post("/api/auth/verify-email", json={"email": email, "code": "123456"})
    assert r.status_code == 200, r.data
    body = r.get_json()
    web_token = body["token"]
    binding_file = body["bindingKeyFile"]
    binding_key = json.loads(binding_file)["key"]
    print("verified", body["fingerprint"])

    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.data

    r = client.post("/api/sync/device/request-code", json={"email": email})
    assert r.status_code == 200, r.data
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        t = EmailToken.query.filter_by(user_id=user.id, purpose="device_bind").order_by(EmailToken.id.desc()).first()
        t.code_hash = hash_token("654321")
        db.session.commit()

    r = client.post(
        "/api/sync/device/bind",
        json={
            "email": email,
            "password": password,
            "bindingKey": binding_key,
            "code": "654321",
            "deviceName": "smoke-pc",
            "platform": "Windows",
            "clientVersion": "0.0.0-test",
        },
    )
    assert r.status_code == 200, r.data
    device_token = r.get_json()["deviceToken"]

    headers = {"Authorization": f"Bearer {device_token}"}
    payload = base64.b64encode(b"encrypted-vault-bytes").decode()
    r = client.put(
        "/api/sync/vault",
        headers=headers,
        json={"baseVersion": 0, "dataBase64": payload},
    )
    assert r.status_code == 200, r.data
    assert r.get_json()["vaultVersion"] == 1

    r = client.put(
        "/api/sync/vault",
        headers=headers,
        json={"baseVersion": 0, "dataBase64": payload},
    )
    assert r.status_code == 409, r.data

    r = client.get("/api/sync/vault", headers=headers)
    assert r.status_code == 200
    assert base64.b64decode(r.get_json()["dataBase64"]) == b"encrypted-vault-bytes"

    r = client.get("/api/me", headers={"Authorization": f"Bearer {web_token}"})
    assert r.status_code == 200, r.data
    assert r.get_json()["vaultVersion"] == 1
    print("smoke ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
