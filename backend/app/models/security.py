"""Persist individual operators, revocable sessions and security audit records."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class OperatorAccount(Base):
    __tablename__ = "operator_accounts"
    __table_args__ = (
        CheckConstraint("role IN ('VIEWER','OPERATOR','ADMIN')", name="valid_role"),
        CheckConstraint("username ~ '^[a-z0-9][a-z0-9_.-]{2,63}$'", name="valid_username"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10))
    active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class OperatorSession(Base):
    __tablename__ = "operator_sessions"
    __table_args__ = (Index("ix_operator_sessions_account", "operator_id"),)

    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    operator_id: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("operator_accounts.id", ondelete="RESTRICT"))
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))


class SecurityAudit(Base):
    __tablename__ = "security_audit_events"
    __table_args__ = (Index("ix_security_audit_operator_action_time", "operator_id", "action", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    operator_id: Mapped[UUID | None] = mapped_column(PGUUID, ForeignKey("operator_accounts.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[UUID | None] = mapped_column(PGUUID)
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class NotificationPolicyDocument(Base):
    __tablename__ = "notification_policy_documents"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    rules: Mapped[list] = mapped_column(JSONB)
