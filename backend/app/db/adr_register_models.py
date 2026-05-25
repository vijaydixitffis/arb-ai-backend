from sqlalchemy import Column, String, Text, Date, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB, TIMESTAMPTZ
from app.core.database import Base
import uuid
from datetime import datetime

class AdrRegister(Base):
    __tablename__ = "adr_register"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    adr_id         = Column(String, unique=True, nullable=False)
    title          = Column(Text, nullable=False)
    status         = Column(String(20), nullable=False, default='draft')
    stage          = Column(String(20), nullable=False, default='authored')
    owner_name     = Column(Text, nullable=False)
    owner_role     = Column(String(30), nullable=False, default='solution_architect')
    owner_user_id  = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    context        = Column(Text)
    decision       = Column(Text)
    rationale      = Column(Text)
    tags           = Column(ARRAY(String), nullable=False, default=list)
    domain         = Column(Text)
    review_date    = Column(Date)
    decided_at     = Column(TIMESTAMPTZ)
    superseded_by  = Column(String, ForeignKey("adr_register.adr_id", ondelete="SET NULL"), nullable=True)
    linked_arb_ref = Column(String)
    options        = Column(JSONB, nullable=False, default=list)
    consequences   = Column(JSONB, nullable=False, default=lambda: {"pos": [], "neg": []})
    links          = Column(JSONB, nullable=False, default=list)
    activity       = Column(JSONB, nullable=False, default=list)
    comment_count  = Column(Integer, nullable=False, default=0)
    created_by     = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at     = Column(TIMESTAMPTZ, nullable=False, default=datetime.utcnow)
    updated_at     = Column(TIMESTAMPTZ, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
