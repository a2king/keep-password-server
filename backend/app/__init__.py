from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, send_from_directory
from flask_cors import CORS

from app.config import Config
from app.extensions import db, migrate


def create_app(config_object: type = Config) -> Flask:
    load_dotenv()
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
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}}, supports_credentials=True)

    from app.api import api_bp

    app.register_blueprint(api_bp)

    releases_root = Path(app.config["VAULT_STORAGE_DIR"]).parent / "releases"
    releases_root.mkdir(parents=True, exist_ok=True)

    @app.get("/downloads/<path:filename>")
    def download_release(filename: str):
        return send_from_directory(releases_root, filename, as_attachment=True)

    register_cli(app)

    with app.app_context():
        db.create_all()

    return app


def register_cli(app: Flask) -> None:
    @app.cli.command("set-admin")
    def set_admin() -> None:
        """用法: flask --app wsgi set-admin  （然后按提示输入邮箱）或 SET_ADMIN_EMAIL=... flask --app wsgi set-admin"""
        import click

        from app.models import User

        email = os.environ.get("SET_ADMIN_EMAIL") or click.prompt("管理员邮箱").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user is None:
            raise SystemExit(f"用户不存在: {email}")
        user.is_admin = True
        db.session.commit()
        click.echo(f"已授予管理员: {email}")
