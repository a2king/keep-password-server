from __future__ import annotations

from flask import current_app, request


def client_ip() -> str:
    """获取客户端 IP。仅当 TRUST_PROXY=true 时才信任 X-Forwarded-For（由 Caddy 等注入）。"""
    if current_app.config.get("TRUST_PROXY"):
        xff = (request.headers.get("X-Forwarded-For") or "").strip()
        if xff:
            # 最左侧为原始客户端（单层可信代理场景）
            return xff.split(",")[0].strip()[:64]
    return (request.remote_addr or "")[:64]
