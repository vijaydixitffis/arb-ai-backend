from fastapi import APIRouter, Depends, HTTPException, Header, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional, Any
import json

from app.core.database import get_db
from app.core.security import decode_access_token
from app.services.admin_service import AdminService
from app.models.admin import (
    ADMIN_ROLES, SUPER_ADMIN_ROLES,
    SystemConfigUpdate,
    UserCreate, UserUpdate, UserPasswordReset,
    DomainUpdate,
    ArtefactTypeCreate, ArtefactTypeUpdate,
    PtxGateCreate, PtxGateUpdate,
    DispositionCreate, DispositionUpdate,
    EAPrincipleCreate, EAPrincipleUpdate,
    ChecklistSubsectionCreate, ChecklistSubsectionUpdate,
    ChecklistQuestionCreate, ChecklistQuestionUpdate,
    PromptTemplateCreate,
)

router = APIRouter()


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _get_user_payload(authorization: Optional[str]) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization.split(" ")[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


def require_admin(authorization: Optional[str] = Header(None)) -> tuple[str, str]:
    payload = _get_user_payload(authorization)
    user_id = payload.get("sub")
    role = payload.get("role")
    if role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required (arb_admin or super_admin)")
    return user_id, role


def require_super_admin(authorization: Optional[str] = Header(None)) -> tuple[str, str]:
    payload = _get_user_payload(authorization)
    user_id = payload.get("sub")
    role = payload.get("role")
    if role not in SUPER_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Super admin access required")
    return user_id, role


# ============================================================================
# SYSTEM CONFIG
# ============================================================================

@router.get("/config")
async def get_all_config(
    admin: tuple = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    rows = service.get_all_config()
    # Group by category
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(row.category, []).append({
            "id": str(row.id),
            "config_key": row.config_key,
            "config_value": row.config_value,
            "data_type": row.data_type,
            "category": row.category,
            "label": row.label,
            "description": row.description,
            "is_editable_by_admin": row.is_editable_by_admin,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        })
    return {"config": grouped}


@router.put("/config/{config_key}")
async def update_config(
    config_key: str,
    update: SystemConfigUpdate,
    admin: tuple = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    user_id, _ = admin
    service = AdminService(db)
    row = service.update_config(config_key, update, user_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Config key '{config_key}' not found")
    return {"config_key": row.config_key, "config_value": row.config_value, "updated": True}


# ============================================================================
# USER MANAGEMENT
# ============================================================================

@router.get("/users")
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    admin: tuple = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    users = service.list_users(skip=skip, limit=limit)
    return {"users": [
        {
            "id": str(u.id),
            "email": u.email,
            "role": u.role,
            "is_active": getattr(u, 'is_active', True),
            "last_login_at": getattr(u, 'last_login_at', None),
            "created_at": u.created_at.isoformat(),
            "updated_at": u.updated_at.isoformat(),
        }
        for u in users
    ]}


@router.post("/users", status_code=201)
async def create_user(
    data: UserCreate,
    admin: tuple = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user_id, _ = admin
    service = AdminService(db)
    try:
        user = service.create_user(data, user_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"id": str(user.id), "email": user.email, "role": user.role, "created": True}


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    data: UserUpdate,
    admin: tuple = Depends(require_admin),
    db: Session = Depends(get_db),
):
    caller_id, _ = admin
    service = AdminService(db)
    user = service.update_user(user_id, data, caller_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": str(user.id), "role": user.role, "is_active": getattr(user, 'is_active', True), "updated": True}


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    data: UserPasswordReset,
    admin: tuple = Depends(require_admin),
    db: Session = Depends(get_db),
):
    caller_id, _ = admin
    service = AdminService(db)
    user = service.reset_user_password(user_id, data.new_password, caller_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user_id, "reset": True}


@router.delete("/users/{user_id}")
async def deactivate_user(
    user_id: str,
    admin: tuple = Depends(require_admin),
    db: Session = Depends(get_db),
):
    caller_id, _ = admin
    service = AdminService(db)
    user = service.deactivate_user(user_id, caller_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user_id, "deactivated": True}


# ============================================================================
# DOMAIN MANAGEMENT
# ============================================================================

@router.get("/domains")
async def list_domains(
    include_inactive: bool = Query(True),
    admin: tuple = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    domains = service.list_domains(include_inactive=include_inactive)
    return {"domains": [
        {
            "id": str(d.id),
            "slug": d.slug,
            "name": d.name,
            "description": d.description,
            "color": d.color,
            "icon": d.icon,
            "seq_number": d.seq_number,
            "is_active": d.is_active,
        }
        for d in domains
    ]}


@router.put("/domains/{domain_id}")
async def update_domain(
    domain_id: str,
    data: DomainUpdate,
    admin: tuple = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user_id, _ = admin
    service = AdminService(db)
    domain = service.update_domain(domain_id, data, user_id)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    return {"id": str(domain.id), "slug": domain.slug, "is_active": domain.is_active, "updated": True}


# ============================================================================
# ARTEFACT TYPES
# ============================================================================

@router.get("/artefact-types")
async def list_artefact_types(
    admin: tuple = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    types = service.list_artefact_types()
    return {"artefact_types": [
        {"id": str(t.id), "value": t.value, "label": t.label, "description": t.description,
         "icon": t.icon, "is_active": t.is_active}
        for t in types
    ]}


@router.post("/artefact-types", status_code=201)
async def create_artefact_type(
    data: ArtefactTypeCreate,
    admin: tuple = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user_id, _ = admin
    service = AdminService(db)
    obj = service.create_artefact_type(data, user_id)
    return {"id": str(obj.id), "value": obj.value, "created": True}


@router.put("/artefact-types/{artefact_type_id}")
async def update_artefact_type(
    artefact_type_id: str,
    data: ArtefactTypeUpdate,
    admin: tuple = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user_id, _ = admin
    service = AdminService(db)
    obj = service.update_artefact_type(artefact_type_id, data, user_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Artefact type not found")
    return {"id": str(obj.id), "updated": True}


@router.delete("/artefact-types/{artefact_type_id}")
async def delete_artefact_type(
    artefact_type_id: str,
    admin: tuple = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user_id, _ = admin
    service = AdminService(db)
    if not service.delete_artefact_type(artefact_type_id, user_id):
        raise HTTPException(status_code=404, detail="Artefact type not found")
    return {"id": artefact_type_id, "deleted": True}


# ============================================================================
# PTX GATES
# ============================================================================

@router.get("/ptx-gates")
async def list_ptx_gates(admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    service = AdminService(db)
    gates = service.list_ptx_gates()
    return {"ptx_gates": [
        {"id": str(g.id), "value": g.value, "label": g.label, "description": g.description,
         "sort_order": g.sort_order, "is_active": g.is_active}
        for g in gates
    ]}


@router.post("/ptx-gates", status_code=201)
async def create_ptx_gate(data: PtxGateCreate, admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    user_id, _ = admin
    obj = AdminService(db).create_ptx_gate(data, user_id)
    return {"id": str(obj.id), "value": obj.value, "created": True}


@router.put("/ptx-gates/{gate_id}")
async def update_ptx_gate(gate_id: str, data: PtxGateUpdate, admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    user_id, _ = admin
    obj = AdminService(db).update_ptx_gate(gate_id, data, user_id)
    if not obj:
        raise HTTPException(status_code=404, detail="PTX gate not found")
    return {"id": str(obj.id), "updated": True}


@router.delete("/ptx-gates/{gate_id}")
async def delete_ptx_gate(gate_id: str, admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    user_id, _ = admin
    if not AdminService(db).delete_ptx_gate(gate_id, user_id):
        raise HTTPException(status_code=404, detail="PTX gate not found")
    return {"id": gate_id, "deleted": True}


# ============================================================================
# ARCHITECTURE DISPOSITIONS
# ============================================================================

@router.get("/dispositions")
async def list_dispositions(admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    service = AdminService(db)
    items = service.list_dispositions()
    return {"dispositions": [
        {"id": str(i.id), "value": i.value, "label": i.label, "description": i.description,
         "sort_order": i.sort_order, "is_active": i.is_active}
        for i in items
    ]}


@router.post("/dispositions", status_code=201)
async def create_disposition(data: DispositionCreate, admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    user_id, _ = admin
    obj = AdminService(db).create_disposition(data, user_id)
    return {"id": str(obj.id), "value": obj.value, "created": True}


@router.put("/dispositions/{disp_id}")
async def update_disposition(disp_id: str, data: DispositionUpdate, admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    user_id, _ = admin
    obj = AdminService(db).update_disposition(disp_id, data, user_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Disposition not found")
    return {"id": str(obj.id), "updated": True}


@router.delete("/dispositions/{disp_id}")
async def delete_disposition(disp_id: str, admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    user_id, _ = admin
    if not AdminService(db).delete_disposition(disp_id, user_id):
        raise HTTPException(status_code=404, detail="Disposition not found")
    return {"id": disp_id, "deleted": True}


# ============================================================================
# EA PRINCIPLES
# ============================================================================

@router.get("/ea-principles")
async def list_ea_principles(admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    service = AdminService(db)
    items = service.list_ea_principles()
    return {"ea_principles": [
        {"id": str(i.id), "principle_code": i.principle_code, "principle_name": i.principle_name,
         "category": i.category, "statement": i.statement, "rationale": i.rationale,
         "arb_weight": i.arb_weight, "is_active": i.is_active}
        for i in items
    ]}


@router.post("/ea-principles", status_code=201)
async def create_ea_principle(data: EAPrincipleCreate, admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    user_id, _ = admin
    obj = AdminService(db).create_ea_principle(data, user_id)
    return {"id": str(obj.id), "principle_code": obj.principle_code, "created": True}


@router.put("/ea-principles/{principle_id}")
async def update_ea_principle(principle_id: str, data: EAPrincipleUpdate, admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    user_id, _ = admin
    obj = AdminService(db).update_ea_principle(principle_id, data, user_id)
    if not obj:
        raise HTTPException(status_code=404, detail="EA principle not found")
    return {"id": str(obj.id), "updated": True}


@router.delete("/ea-principles/{principle_id}")
async def delete_ea_principle(principle_id: str, admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    user_id, _ = admin
    if not AdminService(db).delete_ea_principle(principle_id, user_id):
        raise HTTPException(status_code=404, detail="EA principle not found")
    return {"id": principle_id, "deleted": True}


# ============================================================================
# CHECKLIST MANAGEMENT
# ============================================================================

@router.get("/checklist/subsections")
async def list_subsections(
    domain_id: Optional[str] = Query(None),
    admin: tuple = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    items = service.list_subsections(domain_id=domain_id)
    return {"subsections": [
        {"id": str(i.id), "domain_id": str(i.domain_id), "name": i.name,
         "description": i.description, "color_theme": i.color_theme,
         "sort_order": i.sort_order, "is_active": i.is_active}
        for i in items
    ]}


@router.post("/checklist/subsections", status_code=201)
async def create_subsection(data: ChecklistSubsectionCreate, admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    user_id, _ = admin
    obj = AdminService(db).create_subsection(data, user_id)
    return {"id": str(obj.id), "name": obj.name, "created": True}


@router.put("/checklist/subsections/{sub_id}")
async def update_subsection(sub_id: str, data: ChecklistSubsectionUpdate, admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    user_id, _ = admin
    obj = AdminService(db).update_subsection(sub_id, data, user_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Subsection not found")
    return {"id": str(obj.id), "updated": True}


@router.delete("/checklist/subsections/{sub_id}")
async def delete_subsection(sub_id: str, admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    user_id, _ = admin
    if not AdminService(db).delete_subsection(sub_id, user_id):
        raise HTTPException(status_code=404, detail="Subsection not found")
    return {"id": sub_id, "deleted": True}


@router.get("/checklist/questions")
async def list_questions(
    subsection_id: Optional[str] = Query(None),
    admin: tuple = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    items = service.list_questions(subsection_id=subsection_id)
    return {"questions": [
        {"id": str(i.id), "subsection_id": str(i.subsection_id), "question_code": i.question_code,
         "question_text": i.question_text, "question_type": i.question_type, "help_text": i.help_text,
         "is_required": i.is_required, "sort_order": i.sort_order, "is_active": i.is_active}
        for i in items
    ]}


@router.post("/checklist/questions", status_code=201)
async def create_question(data: ChecklistQuestionCreate, admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    user_id, _ = admin
    obj = AdminService(db).create_question(data, user_id)
    return {"id": str(obj.id), "question_code": obj.question_code, "created": True}


@router.put("/checklist/questions/{q_id}")
async def update_question(q_id: str, data: ChecklistQuestionUpdate, admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    user_id, _ = admin
    obj = AdminService(db).update_question(q_id, data, user_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Question not found")
    return {"id": str(obj.id), "updated": True}


@router.delete("/checklist/questions/{q_id}")
async def delete_question(q_id: str, admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    user_id, _ = admin
    if not AdminService(db).delete_question(q_id, user_id):
        raise HTTPException(status_code=404, detail="Question not found")
    return {"id": q_id, "deleted": True}


# ============================================================================
# ANALYTICS
# ============================================================================

@router.get("/analytics/summary")
async def get_analytics_summary(admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    return AdminService(db).get_analytics_summary()


@router.get("/analytics/domains")
async def get_domain_analytics(admin: tuple = Depends(require_admin), db: Session = Depends(get_db)):
    return {"domains": AdminService(db).get_domain_analytics()}


@router.get("/analytics/recent-reviews")
async def get_recent_reviews(
    limit: int = Query(20, ge=1, le=100),
    admin: tuple = Depends(require_admin),
    db: Session = Depends(get_db),
):
    reviews = AdminService(db).get_recent_reviews(limit=limit)
    return {"reviews": [
        {
            "id": str(r.id),
            "solution_name": r.solution_name,
            "status": r.status,
            "decision": r.decision,
            "aggregate_rag_score": r.aggregate_rag_score,
            "llm_model": r.llm_model,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "agent_run_at": r.agent_run_at.isoformat() if r.agent_run_at else None,
        }
        for r in reviews
    ]}


# ============================================================================
# AUDIT LOG
# ============================================================================

@router.get("/audit-log")
async def get_audit_log(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: tuple = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    rows = service.get_audit_log(limit=limit, offset=offset)
    return {"audit_log": [
        {
            "id": str(r.id),
            "table_name": r.table_name,
            "record_id": r.record_id,
            "field_name": r.field_name,
            "old_value": r.old_value,
            "new_value": r.new_value,
            "changed_by": str(r.changed_by) if r.changed_by else None,
            "changed_at": r.changed_at.isoformat(),
            "change_reason": r.change_reason,
        }
        for r in rows
    ]}


# ============================================================================
# PROMPT MANAGEMENT  (super_admin only)
# ============================================================================

@router.get("/prompts")
async def list_prompts(
    super_admin: tuple = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    items = service.list_prompts()
    return {"prompts": [
        {
            "id": str(p.id),
            "prompt_key": p.prompt_key,
            "prompt_type": p.prompt_type,
            "domain_code": p.domain_code,
            "version": p.version,
            "content": p.content,
            "is_active": p.is_active,
            "notes": p.notes,
            "created_at": p.created_at.isoformat(),
        }
        for p in items
    ]}


@router.get("/prompts/{prompt_key}/history")
async def get_prompt_history(
    prompt_key: str,
    super_admin: tuple = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    items = service.get_prompt_history(prompt_key)
    return {"history": [
        {
            "id": str(p.id),
            "version": p.version,
            "is_active": p.is_active,
            "notes": p.notes,
            "created_at": p.created_at.isoformat(),
        }
        for p in items
    ]}


@router.put("/prompts/{prompt_key}")
async def save_prompt(
    prompt_key: str,
    data: PromptTemplateCreate,
    super_admin: tuple = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    user_id, _ = super_admin
    data.prompt_key = prompt_key
    service = AdminService(db)
    obj = service.save_prompt(data, user_id)
    return {"id": str(obj.id), "prompt_key": obj.prompt_key, "version": obj.version, "saved": True}


@router.post("/prompts/{prompt_key}/revert/{version}")
async def revert_prompt(
    prompt_key: str,
    version: int,
    super_admin: tuple = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    user_id, _ = super_admin
    service = AdminService(db)
    obj = service.revert_prompt(prompt_key, version, user_id)
    if not obj:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_key}' version {version} not found")
    return {"prompt_key": prompt_key, "version": version, "reverted": True}


# ============================================================================
# KNOWLEDGE BASE  (super_admin only) — uses existing knowledge_base table
# ============================================================================

class KbEntryCreate(BaseModel):
    title: str
    content: str
    category: Optional[str] = None
    principle_id: Optional[str] = None

class KbEntryUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    principle_id: Optional[str] = None
    is_active: Optional[bool] = None

def _kb_row(kb) -> dict:
    return {
        "id": str(kb.id),
        "title": kb.title,
        "content": kb.content,
        "category": kb.category,
        "principle_id": kb.principle_id,
        "is_active": kb.is_active,
        "created_at": kb.created_at.isoformat() if kb.created_at else None,
        "updated_at": kb.updated_at.isoformat() if kb.updated_at else None,
    }

@router.get("/kb")
async def list_kb_entries(
    include_inactive: bool = Query(False),
    super_admin: tuple = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    from app.db.artefact_models import KnowledgeBase
    q = db.query(KnowledgeBase)
    if not include_inactive:
        q = q.filter(KnowledgeBase.is_active == True)
    items = q.order_by(KnowledgeBase.category, KnowledgeBase.title).all()
    return {"entries": [_kb_row(r) for r in items]}


@router.post("/kb", status_code=201)
async def create_kb_entry(
    data: KbEntryCreate,
    super_admin: tuple = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    from app.db.artefact_models import KnowledgeBase
    from datetime import datetime
    obj = KnowledgeBase(
        title=data.title, content=data.content,
        category=data.category, principle_id=data.principle_id,
        is_active=True, created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return {"entry": _kb_row(obj)}


@router.put("/kb/{entry_id}")
async def update_kb_entry(
    entry_id: str,
    data: KbEntryUpdate,
    super_admin: tuple = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    from app.db.artefact_models import KnowledgeBase
    from datetime import datetime
    obj = db.query(KnowledgeBase).filter(KnowledgeBase.id == entry_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="KB entry not found")
    for field, val in data.model_dump(exclude_none=True).items():
        setattr(obj, field, val)
    obj.updated_at = datetime.utcnow()
    db.commit()
    return {"id": entry_id, "updated": True}


@router.delete("/kb/{entry_id}")
async def delete_kb_entry(
    entry_id: str,
    super_admin: tuple = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    from app.db.artefact_models import KnowledgeBase
    obj = db.query(KnowledgeBase).filter(KnowledgeBase.id == entry_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="KB entry not found")
    db.delete(obj)
    db.commit()
    return {"id": entry_id, "deleted": True}
