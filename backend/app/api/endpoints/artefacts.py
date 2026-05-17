from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Header
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
from app.core.database import get_db
from app.services.artefact_service import ArtefactService
from app.core.security import decode_access_token
from app.models.artefact import ArtefactResponse, ArtefactChunkResponse, KnowledgeBaseResponse

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
# ARTEFACT ENDPOINTS
# ============================================================================
@router.post("/artefacts/upload")
async def upload_artefact(
    review_id: str = Form(...),
    domain_slug: str = Form(...),
    artefact_name: str = Form(...),
    artefact_type: str = Form(...),
    file: UploadFile = File(...),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload an artefact for a review"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Read file content
    file_content = await file.read()
    
    # Process artefact
    service = ArtefactService(db)
    artefact = await service.process_artefact(
        review_id=uuid.UUID(review_id),
        domain_slug=domain_slug,
        artefact_name=artefact_name,
        artefact_type=artefact_type,
        filename=file.filename,
        file_content=file_content
    )
    
    return ArtefactResponse.model_validate(artefact)

@router.get("/artefacts/review/{review_id}")
async def get_review_artefacts(
    review_id: str,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all artefacts for a review"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    service = ArtefactService(db)
    artefacts = await service.get_artefacts_by_review(uuid.UUID(review_id))
    
    return artefacts

@router.get("/artefacts/chunks/{review_id}")
async def get_review_chunks(
    review_id: str,
    domain_slug: Optional[str] = None,
    limit: int = 50,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get relevant chunks for a review"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    service = ArtefactService(db)
    chunks = await service.get_relevant_chunks(
        review_id=uuid.UUID(review_id),
        domain_slug=domain_slug,
        limit=limit
    )
    
    return chunks

@router.delete("/artefacts/{artefact_id}")
async def delete_artefact(
    artefact_id: str,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an artefact"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    service = ArtefactService(db)
    success = await service.delete_artefact(uuid.UUID(artefact_id))
    
    if not success:
        raise HTTPException(status_code=404, detail="Artefact not found")
    
    return {"message": "Artefact deleted successfully"}

# ============================================================================
# KNOWLEDGE BASE ENDPOINTS
# ============================================================================
@router.get("/knowledge-base/search")
async def search_knowledge_base(
    query: str,
    category: Optional[str] = None,
    limit: int = 5,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Search knowledge base for relevant content"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    service = ArtefactService(db)
    results = await service.search_knowledge_base(
        query=query,
        category=category,
        limit=limit
    )
    
    return results

@router.post("/knowledge-base")
async def create_knowledge_base_entry(
    title: str = Form(...),
    content: str = Form(...),
    category: Optional[str] = Form(None),
    principle_id: Optional[str] = Form(None),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a knowledge base entry"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    from app.db.artefact_models import KnowledgeBase
    
    kb_entry = KnowledgeBase(
        title=title,
        content=content,
        category=category,
        principle_id=principle_id
    )
    
    db.add(kb_entry)
    db.commit()
    db.refresh(kb_entry)
    
    return KnowledgeBaseResponse.model_validate(kb_entry)

@router.get("/knowledge-base")
async def get_knowledge_base(
    category: Optional[str] = None,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get knowledge base entries"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    from app.db.artefact_models import KnowledgeBase
    
    query = db.query(KnowledgeBase).filter(KnowledgeBase.is_active == True)
    
    if category:
        query = query.filter(KnowledgeBase.category == category)
    
    entries = query.all()
    
    return [KnowledgeBaseResponse.model_validate(entry) for entry in entries]
