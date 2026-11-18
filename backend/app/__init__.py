from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from app.config import Config
from app.extensions import db, migrate


def create_app(config_object: type = Config, *, init_db: bool = True) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)

    # 相对 sqlite 路径放到 backend 目录下
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if uri.startswith("sqlite:///./"):
        data_dir = Path(app.root_path).parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = data_dir / "keep_password.db"
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path.as_posix()}"

    Path(app.config["VAULT_STORAGE_DIR"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)

    origins = app.config["CORS_ORIGINS"]
    # credentials + "*" 非法；若误配为 * 则关闭 credentials
    cors_credentials = origins != ["*"]
    CORS(app, resources={r"/api/*": {"origins": origins}}, supports_credentials=cors_credentials)

    from app.api import api_bp
    from app.mail import MailError

    app.register_blueprint(api_bp)

    @app.errorhandler(MailError)
    def handle_mail_error(err: MailError):
        return jsonify({"error": err.public_message}), 503

    releases_root = Path(app.config["VAULT_STORAGE_DIR"]).parent / "releases"
    releases_root.mkdir(parents=True, exist_ok=True)

    @app.get("/downloads/<path:filename>")
    def download_release(filename: str):
        return send_from_directory(releases_root, filename, as_attachment=True)

    register_cli(app)

    if init_db:
        from app.dbutil import ensure_schema

        ensure_schema(app)

    return app


def purge_legacy_keys() -> int:
    """清空服务器上所有能帮助解开保险库或旧版绑定的数据。返回受影响的账号数。

    1.0.1 的服务器不再读写这些列。数据密钥由用户自己保管（.kpkey），服务器只留密文。
    """
    from sqlalchemy import or_

    from app.models import AuditLog, User

    users = User.query.filter(
        or_(
            User.wrapped_kpkey.is_not(None),
            User.wrapped_key_sha256.is_not(None),
            User.binding_key_hash.is_not(None),
        )
    ).all()
    for user in users:
        user.wrapped_kpkey = None
        user.wrapped_key_sha256 = None
        user.wrapped_kpkey_updated_at = None
        user.binding_key_hash = None
        user.binding_key_fingerprint = None
        user.binding_key_created_at = None
        db.session.add(AuditLog(user_id=user.id, action="purge_legacy_keys", detail="", ip=""))
    db.session.commit()
    return len(users)


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db_cmd() -> None:
        """创建/补齐数据库表（可在 gunicorn 启动前单独执行）。"""
        from app.dbutil import ensure_schema

        ensure_schema(app)
        print("database ready")

    @app.cli.command("purge-legacy-keys")
    def purge_legacy_keys_cmd() -> None:
        """清空 0.9.x 留下的密钥包与 .kpbind 哈希。1.0.1 起这些数据已不再使用。"""
        import click

        cleared = purge_legacy_keys()
        click.echo(f"已清空 {cleared} 个账号的旧密钥包与绑定密钥")

    @app.cli.command("set-admin")
    def set_admin() -> None:
        """用法: SET_ADMIN_EMAIL=you@example.com flask --app wsgi set-admin"""
        import click

        from app.models import User

        email = os.environ.get("SET_ADMIN_EMAIL") or click.prompt("管理员邮箱").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user is None:
            raise SystemExit(f"用户不存在: {email}")
        user.is_admin = True
        db.session.commit()
        click.echo(f"已授予管理员: {email}")
