from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date, datetime
from enum import Enum

class AdrStatus(str, Enum):
    draft       = 'draft'
    proposed    = 'proposed'
    accepted    = 'accepted'
    conditional = 'conditional'
    deferred    = 'deferred'
    rejected    = 'rejected'
    published   = 'published'
    evolving    = 'evolving'

class AdrStage(str, Enum):
    authored   = 'authored'
    in_review  = 'in_review'
    published  = 'published'
    evolving   = 'evolving'

class AdrConsequences(BaseModel):
    pos: List[str] = []
    neg: List[str] = []

class AdrOption(BaseModel):
    name:   str
    pros:   str = ''
    cons:   str = ''
    chosen: bool = False

class AdrLink(BaseModel):
    kind:  str
    label: str
    href:  str

class AdrActivityEvent(BaseModel):
    kind: str
    who:  str
    when: str
    text: str

class AdrRegisterBase(BaseModel):
    title:          str
    status:         AdrStatus         = AdrStatus.draft
    stage:          AdrStage          = AdrStage.authored
    owner_name:     str
    owner_role:     str               = 'solution_architect'
    context:        Optional[str]     = None
    decision:       Optional[str]     = None
    rationale:      Optional[str]     = None
    tags:           List[str]         = []
    domain:         Optional[str]     = None
    review_date:    Optional[date]    = None
    decided_at:     Optional[datetime]= None
    superseded_by:  Optional[str]     = None
    linked_arb_ref: Optional[str]     = None
    options:        List[AdrOption]   = []
    consequences:   AdrConsequences   = Field(default_factory=AdrConsequences)
    links:          List[AdrLink]     = []

class AdrRegisterCreate(AdrRegisterBase):
    pass

class AdrRegisterStatusUpdate(BaseModel):
    status: AdrStatus

class AdrRegisterResponse(AdrRegisterBase):
    id:            str
    adr_id:        str
    comment_count: int = 0
    activity:      List[AdrActivityEvent] = []
    created_at:    datetime
    updated_at:    datetime

    class Config:
        from_attributes = True
