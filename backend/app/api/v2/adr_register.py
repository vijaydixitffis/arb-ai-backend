from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.adr_register import (
    AdrRegisterCreate,
    AdrRegisterResponse,
    AdrRegisterStatusUpdate,
)
from app.services.adr_register_service import AdrRegisterService

router = APIRouter()

async def get_current_user(authorization: Optional[str] = Header(None)) -> Optional[str]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_access_token(authorization.split(" ")[1])
    return payload.get("sub") if payload else None

def _svc(db: Session = Depends(get_db)) -> AdrRegisterService:
    return AdrRegisterService(db)

@router.get("", response_model=List[AdrRegisterResponse])
async def list_adrs(
    status: Optional[str] = Query(None),
    stage:  Optional[str] = Query(None),
    tag:    Optional[str] = Query(None),
    limit:  int           = Query(100, le=500),
    offset: int           = Query(0),
    svc: AdrRegisterService = Depends(_svc),
    current_user = Depends(get_current_user),
):
    return svc.list_adrs(status=status, stage=stage, tag=tag, limit=limit, offset=offset)

@router.get("/{adr_id}", response_model=AdrRegisterResponse)
async def get_adr(
    adr_id: str,
    svc: AdrRegisterService = Depends(_svc),
    current_user = Depends(get_current_user),
):
    row = svc.get_adr(adr_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"ADR {adr_id} not found")
    return row

@router.post("", response_model=AdrRegisterResponse, status_code=201)
async def create_adr(
    data: AdrRegisterCreate,
    svc: AdrRegisterService = Depends(_svc),
    current_user = Depends(get_current_user),
):
    return svc.create_adr(data, user_id=current_user)

@router.put("/{adr_id}", response_model=AdrRegisterResponse)
async def update_adr(
    adr_id: str,
    data: AdrRegisterCreate,
    svc: AdrRegisterService = Depends(_svc),
    current_user = Depends(get_current_user),
):
    row = svc.update_adr(adr_id, data)
    if not row:
        raise HTTPException(status_code=404, detail=f"ADR {adr_id} not found")
    return row

@router.patch("/{adr_id}/status", response_model=AdrRegisterResponse)
async def update_status(
    adr_id: str,
    update: AdrRegisterStatusUpdate,
    svc: AdrRegisterService = Depends(_svc),
    current_user = Depends(get_current_user),
):
    row = svc.update_status(adr_id, update)
    if not row:
        raise HTTPException(status_code=404, detail=f"ADR {adr_id} not found")
    return row

@router.delete("/{adr_id}", status_code=204)
async def delete_adr(
    adr_id: str,
    svc: AdrRegisterService = Depends(_svc),
    current_user = Depends(get_current_user),
):
    if not svc.delete_adr(adr_id):
        raise HTTPException(status_code=404, detail=f"ADR {adr_id} not found")
