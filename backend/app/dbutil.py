from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import inspect, text

from app.extensions import db


def _lock_file(fh) -> None:
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)


def _unlock_file(fh) -> None:
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def ensure_schema(app) -> None:
    """进程间加锁建表，避免 gunicorn 多 worker 同时 create_all 竞态。"""
    data_dir = Path(app.config["VAULT_STORAGE_DIR"]).parent
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / ".schema.lock"

    with open(lock_path, "a+b") as fh:
        _lock_file(fh)
        try:
            with app.app_context():
                db.create_all()
                _migrate_sqlite_columns()
        finally:
            _unlock_file(fh)


def _migrate_sqlite_columns() -> None:
    """轻量补列：已有 SQLite 库不会因 create_all 自动加新字段。"""
    bind = db.engine
    if bind.dialect.name != "sqlite":
        return
    insp = inspect(bind)
    if "email_tokens" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("email_tokens")}
    if "attempts" not in cols:
        with bind.begin() as conn:
            conn.execute(text("ALTER TABLE email_tokens ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"))


def init_db_main() -> int:
    """供 entrypoint / `python -m app.dbutil` 在启动 gunicorn 前单独执行一次。"""
    from app import create_app

    app = create_app(init_db=False)
    ensure_schema(app)
    print("database ready", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(init_db_main())
