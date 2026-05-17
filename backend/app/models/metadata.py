from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID

# ============================================================================
# SUBMISSION STEPS
# ============================================================================
class Step(BaseModel):
    id: UUID
    step_order: int
    title: str
    description: Optional[str] = None
    icon: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# DOMAINS
# ============================================================================
class Domain(BaseModel):
    id: UUID
    slug: str
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    seq_number: Optional[int] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# DOMAIN STEPS (MAPPING)
# ============================================================================
class DomainStep(BaseModel):
    id: UUID
    domain_id: UUID
    step_id: UUID
    is_active: bool = True
    created_at: datetime

    class Config:
        from_attributes = True

class DomainStepWithDomain(DomainStep):
    domain: Optional[Domain] = None

# ============================================================================
# ARTEFACT TYPES
# ============================================================================
class ArtefactType(BaseModel):
    id: UUID
    value: str
    label: str
    description: Optional[str] = None
    icon: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# ARTEFACT TEMPLATES
# ============================================================================
class ArtefactTemplate(BaseModel):
    id: UUID
    domain_id: UUID
    artefact_type_id: UUID
    name: str
    description: Optional[str] = None
    is_required: bool = False
    is_active: bool = True
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime
    artefact_type: Optional[ArtefactType] = None

    class Config:
        from_attributes = True

# ============================================================================
# CHECKLIST SUBSECTIONS
# ============================================================================
class ChecklistSubsection(BaseModel):
    id: UUID
    domain_id: UUID
    name: str
    description: Optional[str] = None
    color_theme: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    questions: Optional[List['ChecklistQuestion']] = []

    class Config:
        from_attributes = True

# ============================================================================
# CHECKLIST QUESTIONS
# ============================================================================
class ChecklistQuestion(BaseModel):
    id: UUID
    subsection_id: UUID
    question_code: str
    question_text: str
    question_type: str = 'compliance'
    help_text: Optional[str] = None
    is_required: bool = False
    sort_order: int = 0
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    options: Optional[List['QuestionOption']] = []

    class Config:
        from_attributes = True

# ============================================================================
# QUESTION OPTIONS
# ============================================================================
class QuestionOption(BaseModel):
    id: UUID
    question_id: Optional[UUID] = None
    option_value: str
    option_label: str
    description: Optional[str] = None
    color_code: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True
    created_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# EA PRINCIPLES
# ============================================================================
class EAPrinciple(BaseModel):
    id: UUID
    principle_code: str
    principle_name: str
    category: str
    statement: str
    rationale: Optional[str] = None
    implications: Optional[str] = None
    items_to_verify: Optional[List[str]] = []
    arb_weight: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# PRINCIPLE DOMAINS (MAPPING)
# ============================================================================
class PrincipleDomain(BaseModel):
    id: UUID
    principle_id: UUID
    domain_id: UUID
    relevance_score: int = 1
    created_at: datetime

    class Config:
        from_attributes = True

class PrincipleDomainWithPrinciple(PrincipleDomain):
    ea_principles: Optional[EAPrinciple] = None

# ============================================================================
# PTX GATES
# ============================================================================
class PtxGate(BaseModel):
    id: UUID
    value: str
    label: str
    description: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True
    created_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# ARCHITECTURE DISPOSITIONS
# ============================================================================
class ArchitectureDisposition(BaseModel):
    id: UUID
    value: str
    label: str
    description: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True
    created_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# FORM FIELDS
# ============================================================================
class FormField(BaseModel):
    id: UUID
    step_id: UUID
    field_name: str
    field_label: str
    field_type: str
    placeholder: Optional[str] = None
    is_required: bool = False
    validation_rules: Optional[Dict[str, Any]] = None
    options: Optional[Dict[str, Any]] = None
    sort_order: int = 0
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# RESPONSE MODELS
# ============================================================================
class StepToDomainMapping(BaseModel):
    step_order: int
    domain_slug: str

class PtxGateSimple(BaseModel):
    value: str
    label: str

class ArchitectureDispositionSimple(BaseModel):
    value: str
    label: str

class EAPrincipleWithRelevance(EAPrinciple):
    relevance_score: Optional[int] = None

# Update forward references
ChecklistSubsection.model_rebuild()
ChecklistQuestion.model_rebuild()
