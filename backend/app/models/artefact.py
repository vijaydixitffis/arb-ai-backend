from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID

class ArtefactCreate(BaseModel):
    review_id: UUID
    domain_slug: str
    artefact_name: str
    artefact_type: str
    filename: str
    file_content: bytes = Field(..., exclude=True)  # Exclude from response

class ArtefactResponse(BaseModel):
    id: UUID
    review_id: UUID
    domain_slug: str
    artefact_name: str
    artefact_type: str
    filename: str
    file_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    uploaded_at: datetime
    is_active: bool = True

    class Config:
        from_attributes = True

class ArtefactChunkResponse(BaseModel):
    id: UUID
    artefact_id: UUID
    review_id: UUID
    filename: Optional[str] = None
    chunk_index: int
    chunk_text: str
    created_at: datetime

    class Config:
        from_attributes = True

class KnowledgeBaseCreate(BaseModel):
    title: str
    content: str
    category: Optional[str] = None
    principle_id: Optional[str] = None

class KnowledgeBaseResponse(BaseModel):
    id: UUID
    title: str
    content: str
    category: Optional[str] = None
    principle_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    is_active: bool = True

    class Config:
        from_attributes = True

class KnowledgeBaseSearchResult(BaseModel):
    id: UUID
    title: str
    content: str
    category: Optional[str] = None
    principle_id: Optional[str] = None
    relevance_score: int
