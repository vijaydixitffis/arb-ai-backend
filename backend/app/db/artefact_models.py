from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, LargeBinary, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base
import uuid
from datetime import datetime

class Artefact(Base):
    __tablename__ = "artefacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id = Column(UUID(as_uuid=True), nullable=False)
    domain_slug = Column(String(50), nullable=False)
    artefact_name = Column(String(255), nullable=False)
    artefact_type = Column(String(100), nullable=False)
    filename = Column(Text, nullable=False)
    file_type = Column(String, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    content = Column(LargeBinary, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    chunks = relationship("ArtefactChunk", back_populates="artefact", cascade="all, delete-orphan", foreign_keys="ArtefactChunk.artefact_id")

class ArtefactChunk(Base):
    __tablename__ = "artefact_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    artefact_id = Column(UUID(as_uuid=True), ForeignKey("artefacts.id", ondelete="CASCADE"), nullable=False)
    review_id = Column(UUID(as_uuid=True), nullable=False)
    filename = Column(Text, nullable=True)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    artefact = relationship("Artefact", back_populates="chunks")

class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(100), nullable=True)
    principle_id = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
