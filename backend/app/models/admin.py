from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Any, Dict
from datetime import datetime
from uuid import UUID


# ============================================================================
# ROLES
# ============================================================================
ADMIN_ROLES = {'arb_admin', 'super_admin'}
SUPER_ADMIN_ROLES = {'super_admin'}
ALL_ROLES = {'solution_architect', 'enterprise_architect', 'arb_admin', 'super_admin'}


# ============================================================================
# SYSTEM CONFIG
# ============================================================================
class SystemConfigItem(BaseModel):
    id: UUID
    config_key: str
    config_value: Any
    data_type: str
    category: str
    label: str
    description: Optional[str] = None
    is_editable_by_admin: bool
    updated_by: Optional[UUID] = None
    updated_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SystemConfigUpdate(BaseModel):
    config_value: Any
    change_reason: Optional[str] = None


# ============================================================================
# USER MANAGEMENT
# ============================================================================
class UserOut(BaseModel):
    id: UUID
    email: str
    role: str
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    role: str = 'solution_architect'
    is_active: bool = True


class UserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserPasswordReset(BaseModel):
    new_password: str = Field(min_length=6)


# ============================================================================
# DOMAIN MANAGEMENT
# ============================================================================
class DomainUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    is_active: Optional[bool] = None
    change_reason: Optional[str] = None


# ============================================================================
# ARTEFACT TYPES
# ============================================================================
class ArtefactTypeCreate(BaseModel):
    value: str
    label: str
    description: Optional[str] = None
    icon: Optional[str] = None
    is_active: bool = True


class ArtefactTypeUpdate(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    is_active: Optional[bool] = None


# ============================================================================
# PTX GATES
# ============================================================================
class PtxGateCreate(BaseModel):
    value: str
    label: str
    description: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


class PtxGateUpdate(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


# ============================================================================
# ARCHITECTURE DISPOSITIONS
# ============================================================================
class DispositionCreate(BaseModel):
    value: str
    label: str
    description: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


class DispositionUpdate(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


# ============================================================================
# EA PRINCIPLES
# ============================================================================
class EAPrincipleCreate(BaseModel):
    principle_code: str
    principle_name: str
    category: str
    statement: str
    rationale: Optional[str] = None
    implications: Optional[str] = None
    items_to_verify: Optional[List[str]] = None
    arb_weight: Optional[str] = None
    is_active: bool = True


class EAPrincipleUpdate(BaseModel):
    principle_name: Optional[str] = None
    category: Optional[str] = None
    statement: Optional[str] = None
    rationale: Optional[str] = None
    implications: Optional[str] = None
    items_to_verify: Optional[List[str]] = None
    arb_weight: Optional[str] = None
    is_active: Optional[bool] = None


# ============================================================================
# CHECKLIST
# ============================================================================
class ChecklistSubsectionCreate(BaseModel):
    domain_id: UUID
    name: str
    description: Optional[str] = None
    color_theme: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


class ChecklistSubsectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color_theme: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class ChecklistQuestionCreate(BaseModel):
    subsection_id: UUID
    question_code: str
    question_text: str
    question_type: str = 'compliance'
    help_text: Optional[str] = None
    is_required: bool = False
    sort_order: int = 0
    is_active: bool = True


class ChecklistQuestionUpdate(BaseModel):
    question_text: Optional[str] = None
    question_type: Optional[str] = None
    help_text: Optional[str] = None
    is_required: Optional[bool] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


# ============================================================================
# PROMPT TEMPLATES
# ============================================================================
class PromptTemplateOut(BaseModel):
    id: UUID
    prompt_key: str
    prompt_type: str
    domain_code: Optional[str] = None
    version: int
    content: str
    is_active: bool
    notes: Optional[str] = None
    created_by: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PromptTemplateCreate(BaseModel):
    prompt_key: str
    prompt_type: str = 'system'
    domain_code: Optional[str] = None
    content: str
    notes: Optional[str] = None


class PromptTemplateUpdate(BaseModel):
    content: str
    notes: Optional[str] = None


# ============================================================================
# KB DOCUMENTS
# ============================================================================
class KbDocumentOut(BaseModel):
    id: UUID
    file_name: str
    title: str
    domain_codes: List[str]
    file_path: str
    file_size: Optional[int] = None
    content_hash: Optional[str] = None
    is_active: bool
    uploaded_by: Optional[UUID] = None
    uploaded_at: datetime
    last_indexed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class KbDocumentUpdate(BaseModel):
    title: Optional[str] = None
    domain_codes: Optional[List[str]] = None
    is_active: Optional[bool] = None


# ============================================================================
# ANALYTICS
# ============================================================================
class AnalyticsSummary(BaseModel):
    total_reviews: int
    pending_reviews: int
    approved_reviews: int
    rejected_reviews: int
    deferred_reviews: int
    reviews_this_month: int
    avg_domain_score: Optional[float] = None
    approval_rate: Optional[float] = None


class DomainAnalytics(BaseModel):
    domain_slug: str
    domain_name: str
    avg_score: Optional[float]
    total_reviews: int
    blocker_count: int


# ============================================================================
# AUDIT LOG
# ============================================================================
class AuditLogOut(BaseModel):
    id: UUID
    table_name: str
    record_id: str
    field_name: Optional[str] = None
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    changed_by: Optional[UUID] = None
    changed_at: datetime
    change_reason: Optional[str] = None

    class Config:
        from_attributes = True
