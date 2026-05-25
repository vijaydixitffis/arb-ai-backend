from sqlalchemy.orm import Session
from sqlalchemy import func, text
from app.db.adr_register_models import AdrRegister
from app.models.adr_register import AdrRegisterCreate, AdrRegisterStatusUpdate
from typing import List, Optional
import uuid

class AdrRegisterService:
    def __init__(self, db: Session):
        self.db = db

    def _next_adr_id(self) -> str:
        result = self.db.execute(text("SELECT nextval('adr_register_seq')")).scalar()
        return f"ADR-{str(result).zfill(3)}"

    def list_adrs(
        self,
        status: Optional[str] = None,
        stage: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AdrRegister]:
        q = self.db.query(AdrRegister)
        if status:
            q = q.filter(AdrRegister.status == status)
        if stage:
            q = q.filter(AdrRegister.stage == stage)
        if tag:
            q = q.filter(AdrRegister.tags.contains([tag]))
        return q.order_by(AdrRegister.created_at.desc()).limit(limit).offset(offset).all()

    def get_adr(self, adr_id: str) -> Optional[AdrRegister]:
        return self.db.query(AdrRegister).filter(AdrRegister.adr_id == adr_id).first()

    def create_adr(self, data: AdrRegisterCreate, user_id: Optional[str] = None) -> AdrRegister:
        row = AdrRegister(
            adr_id        = self._next_adr_id(),
            title         = data.title,
            status        = data.status.value,
            stage         = data.stage.value,
            owner_name    = data.owner_name,
            owner_role    = data.owner_role,
            owner_user_id = uuid.UUID(user_id) if user_id else None,
            context       = data.context,
            decision      = data.decision,
            rationale     = data.rationale,
            tags          = data.tags,
            domain        = data.domain,
            review_date   = data.review_date,
            decided_at    = data.decided_at,
            superseded_by = data.superseded_by,
            linked_arb_ref= data.linked_arb_ref,
            options       = [o.model_dump() for o in data.options],
            consequences  = data.consequences.model_dump(),
            links         = [l.model_dump() for l in data.links],
            created_by    = uuid.UUID(user_id) if user_id else None,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_status(self, adr_id: str, update: AdrRegisterStatusUpdate) -> Optional[AdrRegister]:
        row = self.get_adr(adr_id)
        if not row:
            return None
        row.status = update.status.value
        # Auto-advance stage on key status transitions
        if update.status.value in ('accepted', 'conditional'):
            row.stage = 'in_review'
        elif update.status.value == 'published':
            row.stage = 'published'
        elif update.status.value in ('evolving',):
            row.stage = 'evolving'
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_adr(self, adr_id: str, data: AdrRegisterCreate) -> Optional[AdrRegister]:
        row = self.get_adr(adr_id)
        if not row:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            if field == 'options':
                value = [o if isinstance(o, dict) else o.model_dump() for o in data.options]
            elif field == 'consequences':
                value = data.consequences.model_dump()
            elif field == 'links':
                value = [l if isinstance(l, dict) else l.model_dump() for l in data.links]
            elif field in ('status', 'stage'):
                value = value.value if hasattr(value, 'value') else value
            setattr(row, field, value)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete_adr(self, adr_id: str) -> bool:
        row = self.get_adr(adr_id)
        if not row:
            return False
        self.db.delete(row)
        self.db.commit()
        return True
