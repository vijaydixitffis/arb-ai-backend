from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from app.core.database import get_db
from app.services.metadata_service import MetadataService
from app.core.security import decode_access_token

router = APIRouter()

async def get_current_user(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """Extract user ID from JWT token"""
    if not authorization:
        return None
    if not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ")[1]
    payload = decode_access_token(token)
    if not payload:
        return None
    return payload.get("sub")

# ============================================================================
# STEPS ENDPOINTS
# ============================================================================
@router.get("/steps")
async def get_steps(current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all submission steps"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_steps()

# ============================================================================
# DOMAINS ENDPOINTS
# ============================================================================
@router.get("/domains")
async def get_domains(current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all domains"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_domains()

@router.get("/domains/seq-number/{seq_number}")
async def get_domain_by_seq_number(seq_number: int, current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get a domain by its sequence number"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_domain_by_seq_number(seq_number)

@router.get("/domains/step/{step_id}")
async def get_domains_for_step(step_id: str, current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get domains for a specific step"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_domains_for_step(step_id)

@router.get("/domains/step-mapping")
async def get_step_to_domain_mapping(current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get mapping of step_order to domain_slug"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_step_to_domain_mapping()

# ============================================================================
# ARTEFACT TYPES ENDPOINTS
# ============================================================================
@router.get("/artefact-types")
async def get_artefact_types(current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all artefact types"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_artefact_types()

# ============================================================================
# ARTEFACT TEMPLATES ENDPOINTS
# ============================================================================
@router.get("/artefact-templates/domain/{domain_slug}")
async def get_artefact_templates(domain_slug: str, current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get artefact templates for a specific domain"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_artefact_templates(domain_slug)

# ============================================================================
# CHECKLIST SUBSECTIONS ENDPOINTS
# ============================================================================
@router.get("/checklist-subsections/domain/{domain_slug}")
async def get_checklist_subsections(domain_slug: str, current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get checklist subsections for a specific domain"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_checklist_subsections(domain_slug)

# ============================================================================
# PTX GATES ENDPOINTS
# ============================================================================
@router.get("/ptx-gates")
async def get_ptx_gates(current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all PTX gates"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_ptx_gates()

# ============================================================================
# ARCHITECTURE DISPOSITIONS ENDPOINTS
# ============================================================================
@router.get("/architecture-dispositions")
async def get_architecture_dispositions(current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all architecture dispositions"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_architecture_dispositions()

# ============================================================================
# EA PRINCIPLES ENDPOINTS
# ============================================================================
@router.get("/ea-principles")
async def get_ea_principles(current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all EA principles"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_ea_principles()

@router.get("/ea-principles/domain/{domain_slug}")
async def get_ea_principles_for_domain(domain_slug: str, current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get EA principles for a specific domain"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_ea_principles_for_domain(domain_slug)

# ============================================================================
# FORM FIELDS ENDPOINTS
# ============================================================================
@router.get("/form-fields/step/{step_id}")
async def get_form_fields(step_id: str, current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get form fields for a specific step"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_form_fields(step_id)

# ============================================================================
# QUESTION OPTIONS ENDPOINTS
# ============================================================================
@router.get("/question-options/question/{question_id}")
async def get_question_options(question_id: str, current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get question options for a specific question"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_question_options(question_id)

@router.get("/question-options")
async def get_all_question_options(current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all question options"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_all_question_options()

# ============================================================================
# ALL METADATA ENDPOINT
# ============================================================================
@router.get("/all")
async def get_all_metadata(current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all metadata in a single call"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    service = MetadataService(db)
    return service.get_all_metadata()
