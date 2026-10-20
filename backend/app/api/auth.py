from __future__ import annotations

from datetime import timedelta

from email_validator import EmailNotValidError, validate_email
from flask import current_app, jsonify, request

from app.api import api_bp
from app.captcha import create_captcha, verify_captcha
from app.extensions import db
from app.mail import send_mail
from app.models import AuditLog, LoginFailure, User, utcnow
from app.security import generate_binding_key, hash_password, issue_web_token, verify_password
from app.tokens import consume_email_code, send_reset_email, send_verify_email


def _client_ip() -> str:
    return (request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:64]


def _audit(user: User | None, action: str, detail: str = "") -> None:
    db.session.add(
        AuditLog(user_id=user.id if user else None, action=action, detail=detail, ip=_client_ip())
    )


def _normalize_email(raw: str) -> str:
    info = validate_email(raw, check_deliverability=False)
    return info.normalized.lower()


def _recent_failures(email: str) -> int:
    since = utcnow() - timedelta(seconds=current_app.config["LOGIN_FAIL_WINDOW_SECONDS"])
    return LoginFailure.query.filter(LoginFailure.email == email, LoginFailure.created_at >= since).count()


@api_bp.get("/health")
def health():
    return jsonify({"ok": True, "service": "keep-password-server"})


@api_bp.get("/auth/captcha")
def captcha():
    challenge_id, question = create_captcha()
    return jsonify({"challengeId": challenge_id, "question": question})


@api_bp.post("/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    try:
        email = _normalize_email(data.get("email", ""))
    except EmailNotValidError:
        return jsonify({"error": "邮箱格式不正确"}), 400

    password = data.get("password") or ""
    if len(password) < current_app.config["PASSWORD_MIN_LENGTH"]:
        return jsonify({"error": f"密码至少 {current_app.config['PASSWORD_MIN_LENGTH']} 位"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "该邮箱已注册"}), 409

    user = User(email=email, password_hash=hash_password(password), is_verified=False)
    db.session.add(user)
    _audit(user, "register")
    db.session.commit()
    send_verify_email(user)
    return jsonify({"ok": True, "message": "注册成功，请查收邮箱验证码"}), 201


@api_bp.post("/auth/verify-email")
def verify_email():
    data = request.get_json(silent=True) or {}
    try:
        email = _normalize_email(data.get("email", ""))
    except EmailNotValidError:
        return jsonify({"error": "邮箱格式不正确"}), 400

    user = User.query.filter_by(email=email).first()
    if user is None:
        return jsonify({"error": "用户不存在"}), 404
    if user.is_verified and user.binding_key_hash:
        return jsonify({"error": "邮箱已验证"}), 400
    if not consume_email_code(user, "verify", data.get("code", "")):
        return jsonify({"error": "验证码不正确或已过期"}), 400

    raw_key, fingerprint, key_hash = generate_binding_key()
    user.is_verified = True
    user.binding_key_hash = key_hash
    user.binding_key_fingerprint = fingerprint
    user.binding_key_created_at = utcnow()
    _audit(user, "verify_email", fingerprint)
    db.session.commit()

    filename = f"keep-password-binding-{fingerprint}.kpbind"
    content = (
        "{\n"
        f'  "format": "keep-password-binding",\n'
        f'  "version": 1,\n'
        f'  "email": "{user.email}",\n'
        f'  "key": "{raw_key}",\n'
        f'  "fingerprint": "{fingerprint}",\n'
        '  "notice": "此文件用于绑定新设备。请妥善保管；在官网重新生成后旧文件立即失效。"\n'
        "}\n"
    )
    return jsonify(
        {
            "ok": True,
            "fingerprint": fingerprint,
            "filename": filename,
            "bindingKeyFile": content,
            "token": issue_web_token(user),
        }
    )


@api_bp.post("/auth/resend-verify")
def resend_verify():
    data = request.get_json(silent=True) or {}
    try:
        email = _normalize_email(data.get("email", ""))
    except EmailNotValidError:
        return jsonify({"error": "邮箱格式不正确"}), 400
    user = User.query.filter_by(email=email).first()
    if user is None:
        return jsonify({"ok": True})
    if user.is_verified:
        return jsonify({"error": "邮箱已验证"}), 400
    send_verify_email(user)
    return jsonify({"ok": True})


@api_bp.post("/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    try:
        email = _normalize_email(data.get("email", ""))
    except EmailNotValidError:
        return jsonify({"error": "邮箱格式不正确"}), 400

    failures = _recent_failures(email)
    need_captcha = failures >= current_app.config["CAPTCHA_AFTER_FAILURES"]
    if need_captcha and not verify_captcha(data.get("captchaId"), data.get("captchaAnswer")):
        return jsonify({"error": "请完成图形验证码", "captchaRequired": True}), 400

    user = User.query.filter_by(email=email).first()
    password = data.get("password") or ""
    if user is None or not verify_password(user.password_hash, password):
        db.session.add(LoginFailure(user_id=user.id if user else None, email=email, ip=_client_ip()))
        db.session.commit()
        return jsonify(
            {
                "error": "邮箱或密码不正确",
                "captchaRequired": _recent_failures(email) >= current_app.config["CAPTCHA_AFTER_FAILURES"],
            }
        ), 401

    if user.is_disabled:
        return jsonify({"error": "账号已禁用"}), 403
    if not user.is_verified:
        return jsonify({"error": "请先完成邮箱验证", "needVerify": True}), 403
    if failures >= current_app.config["LOGIN_FAIL_LIMIT"]:
        return jsonify({"error": "失败次数过多，请稍后再试", "captchaRequired": True}), 429

    user.last_login_at = utcnow()
    _audit(user, "login")
    db.session.commit()
    return jsonify(
        {
            "token": issue_web_token(user),
            "email": user.email,
            "isAdmin": user.is_admin,
            "bindingKeyFingerprint": user.binding_key_fingerprint,
        }
    )


@api_bp.post("/auth/forgot-password")
def forgot_password():
    data = request.get_json(silent=True) or {}
    try:
        email = _normalize_email(data.get("email", ""))
    except EmailNotValidError:
        return jsonify({"error": "邮箱格式不正确"}), 400
    user = User.query.filter_by(email=email).first()
    if user and user.is_verified:
        send_reset_email(user)
    return jsonify({"ok": True, "message": "如果邮箱已注册，将收到重置验证码"})


@api_bp.post("/auth/reset-password")
def reset_password():
    data = request.get_json(silent=True) or {}
    try:
        email = _normalize_email(data.get("email", ""))
    except EmailNotValidError:
        return jsonify({"error": "邮箱格式不正确"}), 400
    password = data.get("password") or ""
    if len(password) < current_app.config["PASSWORD_MIN_LENGTH"]:
        return jsonify({"error": f"密码至少 {current_app.config['PASSWORD_MIN_LENGTH']} 位"}), 400
    user = User.query.filter_by(email=email).first()
    if user is None or not consume_email_code(user, "reset", data.get("code", "")):
        return jsonify({"error": "验证码不正确或已过期"}), 400
    user.password_hash = hash_password(password)
    user.wrapped_kpkey = None
    user.wrapped_kpkey_updated_at = None
    _audit(user, "reset_password")
    db.session.commit()
    send_mail(
        user.email,
        "Keep Password 密码已重置",
        "账号密码已重置。云端加密的保险库密钥包已清除，请在已绑定设备上用新密码重新上传，或在新设备手动导入 .kpkey。",
    )
    return jsonify({"ok": True, "token": issue_web_token(user)})
