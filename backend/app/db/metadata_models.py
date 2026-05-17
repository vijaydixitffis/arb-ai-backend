from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text, ARRAY, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base
import uuid
from datetime import datetime

# ============================================================================
# SUBMISSION STEPS
# ============================================================================
class SubmissionStep(Base):
    __tablename__ = "submission_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    step_order = Column(Integer, unique=True, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

# ============================================================================
# DOMAINS
# ============================================================================
class Domain(Base):
    __tablename__ = "domains"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String, nullable=True)
    icon = Column(String, nullable=True)
    seq_number = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

# ============================================================================
# DOMAIN STEPS (MAPPING)
# ============================================================================
class DomainStep(Base):
    __tablename__ = "domain_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id = Column(UUID(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    step_id = Column(UUID(as_uuid=True), ForeignKey("submission_steps.id", ondelete="CASCADE"), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    domain = relationship("Domain", backref="domain_steps")
    step = relationship("SubmissionStep", backref="domain_steps")

# ============================================================================
# ARTEFACT TYPES
# ============================================================================
class ArtefactType(Base):
    __tablename__ = "artefact_types"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    value = Column(String, unique=True, nullable=False)
    label = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

# ============================================================================
# ARTEFACT TEMPLATES
# ============================================================================
class ArtefactTemplate(Base):
    __tablename__ = "artefact_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id = Column(UUID(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    artefact_type_id = Column(UUID(as_uuid=True), ForeignKey("artefact_types.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_required = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    domain = relationship("Domain", backref="artefact_templates")
    artefact_type = relationship("ArtefactType", backref="artefact_templates")

# ============================================================================
# CHECKLIST SUBSECTIONS
# ============================================================================
class ChecklistSubsection(Base):
    __tablename__ = "checklist_subsections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id = Column(UUID(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    color_theme = Column(String, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    domain = relationship("Domain", backref="checklist_subsections")

# ============================================================================
# CHECKLIST QUESTIONS
# ============================================================================
class ChecklistQuestion(Base):
    __tablename__ = "checklist_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subsection_id = Column(UUID(as_uuid=True), ForeignKey("checklist_subsections.id", ondelete="CASCADE"), nullable=False)
    question_code = Column(String, unique=True, nullable=False)
    question_text = Column(String, nullable=False)
    question_type = Column(String, default="compliance", nullable=False)
    help_text = Column(Text, nullable=True)
    is_required = Column(Boolean, default=False, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    subsection = relationship("ChecklistSubsection", backref="checklist_questions")

# ============================================================================
# QUESTION OPTIONS
# ============================================================================
class QuestionOption(Base):
    __tablename__ = "question_options"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id = Column(UUID(as_uuid=True), ForeignKey("checklist_questions.id", ondelete="CASCADE"), nullable=False)
    option_value = Column(String, nullable=False)
    option_label = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    color_code = Column(String, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    question = relationship("ChecklistQuestion", backref="question_options")

# ============================================================================
# EA PRINCIPLES
# ============================================================================
class EAPrinciple(Base):
    __tablename__ = "ea_principles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    principle_code = Column(String, unique=True, nullable=False)
    principle_name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    statement = Column(String, nullable=False)
    rationale = Column(Text, nullable=True)
    implications = Column(Text, nullable=True)
    items_to_verify = Column(ARRAY(String), nullable=True)
    arb_weight = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

# ============================================================================
# PRINCIPLE DOMAINS (MAPPING)
# ============================================================================
class PrincipleDomain(Base):
    __tablename__ = "principle_domains"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    principle_id = Column(UUID(as_uuid=True), ForeignKey("ea_principles.id", ondelete="CASCADE"), nullable=False)
    domain_id = Column(UUID(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    relevance_score = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    principle = relationship("EAPrinciple", backref="principle_domains")
    domain = relationship("Domain", backref="principle_domains")

# ============================================================================
# PTX GATES
# ============================================================================
class PtxGate(Base):
    __tablename__ = "ptx_gates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    value = Column(String, unique=True, nullable=False)
    label = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

# ============================================================================
# ARCHITECTURE DISPOSITIONS
# ============================================================================
class ArchitectureDisposition(Base):
    __tablename__ = "architecture_dispositions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    value = Column(String, unique=True, nullable=False)
    label = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

# ============================================================================
# FORM FIELDS
# ============================================================================
class FormField(Base):
    __tablename__ = "form_fields"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    step_id = Column(UUID(as_uuid=True), ForeignKey("submission_steps.id", ondelete="CASCADE"), nullable=False)
    field_name = Column(String, nullable=False)
    field_label = Column(String, nullable=False)
    field_type = Column(String, nullable=False)
    placeholder = Column(Text, nullable=True)
    is_required = Column(Boolean, default=False, nullable=False)
    validation_rules = Column(JSONB, nullable=True)
    options = Column(JSONB, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    step = relationship("SubmissionStep", backref="form_fields")
