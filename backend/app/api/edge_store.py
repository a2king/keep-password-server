from __future__ import annotations

import re

from flask import abort, current_app, redirect

from app.api import api_bp

# 只允许 Edge 加载项详情页，拒绝分类/搜索页，避免开放重定向或误判成功。
_DETAIL_URL = re.compile(
    r"^https://microsoftedge\.microsoft\.com/addons/detail/(?:[a-z0-9-]+/)?[a-p]{32}/?$",
    re.I,
)


def edge_store_target(raw: str | None) -> str | None:
    target = (raw or "").strip()
    if not _DETAIL_URL.fullmatch(target):
        return None
    return target.rstrip("/")


@api_bp.get("/edge-store")
def edge_store():
    target = edge_store_target(current_app.config.get("EDGE_STORE_URL"))
    if not target:
        abort(404)
    return redirect(target, code=302)
