from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime

class ChecklistOption(str, Enum):
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    PARTIAL = "partial"
    NA = "na"

class ChecklistItem(BaseModel):
    id: str
    question: str
    answer: ChecklistOption
    evidence_notes: Optional[str] = None

class IntegrationCatalogueItem(BaseModel):
    id: str
    system_name: str
    interface_type: str
    protocol: str
    data_format: str
    frequency: str
    security: str
    notes: Optional[str] = None

class Artefact(BaseModel):
    id: str
    file_name: str
    file_type: str
    file_size: int
    system_label: str
    upload_date: datetime
    file_path: str

class DomainSection(BaseModel):
    domain: str
    checklist_items: List[ChecklistItem]
    integration_catalogue: Optional[List[IntegrationCatalogueItem]] = None
    artefacts: List[Artefact]
    notes: Optional[str] = None

class NFRCriteria(BaseModel):
    category: str
    criteria: str
    target_value: str
    actual_value: str
    score: int = Field(ge=1, le=5)
    evidence: Optional[str] = None

class ARBSubmission(BaseModel):
    id: Optional[str] = None
    project_name: str
    solution_architect_id: str
    status: str = "draft"
    created_date: Optional[datetime] = None
    submitted_date: Optional[datetime] = None
    
    # Step 1: Solution Context
    problem_statement: str
    stakeholders: List[str]
    business_drivers: List[str]
    growth_plans: Optional[str] = None
    
    # Steps 2-7: Domain Sections
    application_architecture: Optional[DomainSection] = None
    integration_architecture: Optional[DomainSection] = None
    data_architecture: Optional[DomainSection] = None
    security_architecture: Optional[DomainSection] = None
    infrastructure_architecture: Optional[DomainSection] = None
    devsecops: Optional[DomainSection] = None
    
    # Step 8: NFR Assessment
    nfr_criteria: List[NFRCriteria]
    
    # Overall progress
    overall_progress: float = 0.0

class ARBReview(BaseModel):
    id: Optional[str] = None
    submission_id: str
    enterprise_architect_id: str
    review_date: Optional[datetime] = None
    agent_recommendation: str
    agent_rationale: str
    ea_decision: str
    ea_override_rationale: Optional[str] = None
    adrs: List[Dict[str, Any]]
    action_register: List[Dict[str, Any]]
    status: str = "pending"

class Decision(str, Enum):
    APPROVE = "approve"
    APPROVE_WITH_ACTIONS = "approve_with_actions"
    DEFER = "defer"
    REJECT = "reject"
