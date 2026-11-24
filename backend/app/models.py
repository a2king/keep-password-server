from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 0.9.x 的 .kpbind 绑定密钥。1.0.1 起不再生成、不再校验；列保留到运维执行 purge-legacy-keys 清空。
    binding_key_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    binding_key_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    binding_key_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vault_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    vault_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    vault_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 0.9.1 用网站密码包裹的数据密钥。1.0.1 起不再写入、不再下发；建立或换钥时清空，
    # 其余由运维执行 purge-legacy-keys 清空。服务器不应持有任何能解开保险库的数据。
    wrapped_kpkey: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    wrapped_kpkey_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 0 = 尚未建立密钥代。换钥或首次原子建立后递增。与 vault_version 一起条件更新。
    key_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wrapped_key_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 当前云端密文所用数据密钥的标识：SHA-256 前 12 位十六进制，与客户端 .kpkey 文件名中的编号相同。
    # 只用于提示用户该选哪一份密钥文件、拦截用错密钥的上传，不能用来解密。
    vault_key_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    devices: Mapped[list[Device]] = relationship(back_populates="user", cascade="all, delete-orphan")
    tokens: Mapped[list[EmailToken]] = relationship(back_populates="user", cascade="all, delete-orphan")
    login_failures: Mapped[list[LoginFailure]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Device(db.Model):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="未命名设备")
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    platform: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    client_version: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="devices")

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class EmailToken(db.Model):
    __tablename__ = "email_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="tokens")


class LoginFailure(db.Model):
    __tablename__ = "login_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped[User | None] = relationship(back_populates="login_failures")


class CaptchaChallenge(db.Model):
    __tablename__ = "captcha_challenges"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    answer_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SyncEvent(db.Model):
    """轻量统计：每日同步次数（管理看板用）。"""

    __tablename__ = "sync_events"
    __table_args__ = (UniqueConstraint("day", "user_id", name="uq_sync_day_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    day: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class AuthThrottle(db.Model):
    """忘记密码等敏感操作的简易限流桶（email hash / IP）。"""

    __tablename__ = "auth_throttles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bucket_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DeviceBindCodeRequest(db.Model):
    """设备绑定验证码请求限流。只存规范化邮箱哈希和 IP，不存明文邮箱。

    email_hash 仅在本次请求通过限流、占用邮箱额度时写入；被 429 拦截的请求只记 IP。
    """

    __tablename__ = "device_bind_code_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class DevicePairing(db.Model):
    """新设备向已绑定设备请求数据密钥的一次性会话。

    服务器只转发：新设备公钥的承诺与公钥、批准设备的公钥、用两边临时密钥加密的密钥信封。
    这些都不能用来解密保险库。会话几分钟后过期，完成后清空公钥和信封。
    """

    __tablename__ = "device_pairings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    requester_device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    approver_device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    # requested -> offered -> revealed -> approved -> completed；任一阶段可 rejected / cancelled，或过期。
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="requested")
    commitment: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_public_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approver_public_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    envelope: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
