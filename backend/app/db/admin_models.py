from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from app.core.database import Base
import uuid
from datetime import datetime


class SystemConfig(Base):
    __tablename__ = "system_config"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    config_key           = Column(String, unique=True, nullable=False)
    config_value         = Column(JSONB, nullable=False, default={})
    data_type            = Column(String, nullable=False, default='string')
    category             = Column(String, nullable=False, default='general')
    label                = Column(String, nullable=False)
    description          = Column(Text, nullable=True)
    is_editable_by_admin = Column(Boolean, nullable=False, default=True)
    updated_by           = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at           = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at           = Column(DateTime(timezone=True), default=datetime.utcnow)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_key  = Column(String, nullable=False)
    prompt_type = Column(String, nullable=False, default='system')
    domain_code = Column(String, nullable=True)
    version     = Column(Integer, nullable=False, default=1)
    content     = Column(Text, nullable=False)
    is_active   = Column(Boolean, nullable=False, default=True)
    notes       = Column(Text, nullable=True)
    created_by  = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at  = Column(DateTime(timezone=True), default=datetime.utcnow)


class KbDocument(Base):
    __tablename__ = "kb_documents"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_name       = Column(String, nullable=False)
    title           = Column(String, nullable=False)
    domain_codes    = Column(ARRAY(String), nullable=False, default=[])
    file_path       = Column(String, nullable=False)
    file_size       = Column(Integer, nullable=True)
    content_hash    = Column(String, nullable=True)
    is_active       = Column(Boolean, nullable=False, default=True)
    uploaded_by     = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploaded_at     = Column(DateTime(timezone=True), default=datetime.utcnow)
    last_indexed_at = Column(DateTime(timezone=True), nullable=True)


class ConfigAuditLog(Base):
    __tablename__ = "config_audit_log"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_name    = Column(String, nullable=False)
    record_id     = Column(String, nullable=False)
    field_name    = Column(String, nullable=True)
    old_value     = Column(JSONB, nullable=True)
    new_value     = Column(JSONB, nullable=True)
    changed_by    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_at    = Column(DateTime(timezone=True), default=datetime.utcnow)
    change_reason = Column(Text, nullable=True)
