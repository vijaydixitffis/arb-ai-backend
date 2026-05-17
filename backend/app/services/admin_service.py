import hashlib
import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.db.admin_models import ConfigAuditLog, KbDocument, PromptTemplate, SystemConfig
from app.db.metadata_models import (
    ArchitectureDisposition,
    ArtefactType,
    ChecklistQuestion,
    ChecklistSubsection,
    Domain,
    EAPrinciple,
    PtxGate,
)
from app.db.review_models import Blocker, DomainScore, Review
from app.db.user_models import User
from app.models.admin import (
    ArtefactTypeCreate,
    ArtefactTypeUpdate,
    ChecklistQuestionCreate,
    ChecklistQuestionUpdate,
    ChecklistSubsectionCreate,
    ChecklistSubsectionUpdate,
    DispositionCreate,
    DispositionUpdate,
    DomainUpdate,
    EAPrincipleCreate,
    EAPrincipleUpdate,
    KbDocumentUpdate,
    PromptTemplateCreate,
    PromptTemplateUpdate,
    PtxGateCreate,
    PtxGateUpdate,
    SystemConfigUpdate,
    UserCreate,
    UserUpdate,
)

KB_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'knowledge-base')


class AdminService:
    def __init__(self, db: Session):
        self.db = db

    # ── Audit helper ──────────────────────────────────────────────────────────

    def _audit(
        self,
        table: str,
        record_id: str,
        field: Optional[str],
        old_val: Any,
        new_val: Any,
        changed_by: Optional[str],
        reason: Optional[str] = None,
    ) -> None:
        log = ConfigAuditLog(
            table_name=table,
            record_id=record_id,
            field_name=field,
            old_value=old_val,
            new_value=new_val,
            changed_by=UUID(changed_by) if changed_by else None,
            change_reason=reason,
        )
        self.db.add(log)

    # =========================================================================
    # SYSTEM CONFIG
    # =========================================================================

    def get_all_config(self) -> List[SystemConfig]:
        return self.db.query(SystemConfig).order_by(SystemConfig.category, SystemConfig.config_key).all()

    def get_config_by_category(self, category: str) -> List[SystemConfig]:
        return self.db.query(SystemConfig).filter(SystemConfig.category == category).order_by(SystemConfig.config_key).all()

    def update_config(self, config_key: str, update: SystemConfigUpdate, user_id: str) -> Optional[SystemConfig]:
        row = self.db.query(SystemConfig).filter(SystemConfig.config_key == config_key).first()
        if not row:
            return None
        old_val = row.config_value
        row.config_value = update.config_value
        row.updated_by = UUID(user_id)
        row.updated_at = datetime.utcnow()
        self._audit('system_config', str(row.id), config_key, old_val, update.config_value, user_id, update.change_reason)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_audit_log(self, limit: int = 100, offset: int = 0) -> List[ConfigAuditLog]:
        return (
            self.db.query(ConfigAuditLog)
            .order_by(ConfigAuditLog.changed_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    # =========================================================================
    # USER MANAGEMENT
    # =========================================================================

    def list_users(self, skip: int = 0, limit: int = 100) -> List[User]:
        return self.db.query(User).order_by(User.created_at.desc()).offset(skip).limit(limit).all()

    def get_user(self, user_id: str) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def create_user(self, data: UserCreate, created_by: str) -> User:
        existing = self.db.query(User).filter(User.email == data.email).first()
        if existing:
            raise ValueError(f"User with email {data.email} already exists")
        user = User(
            email=data.email,
            user_password=get_password_hash(data.password),
            role=data.role,
            is_active=data.is_active,
            created_by=UUID(created_by),
        )
        self.db.add(user)
        self.db.flush()
        self._audit('users', str(user.id), 'created', None, {'email': data.email, 'role': data.role}, created_by)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_user(self, user_id: str, data: UserUpdate, changed_by: str) -> Optional[User]:
        user = self.get_user(user_id)
        if not user:
            return None
        if data.role is not None:
            self._audit('users', user_id, 'role', user.role, data.role, changed_by)
            user.role = data.role
        if data.is_active is not None:
            self._audit('users', user_id, 'is_active', user.is_active, data.is_active, changed_by)
            user.is_active = data.is_active
        user.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(user)
        return user

    def reset_user_password(self, user_id: str, new_password: str, changed_by: str) -> Optional[User]:
        user = self.get_user(user_id)
        if not user:
            return None
        user.user_password = get_password_hash(new_password)
        user.updated_at = datetime.utcnow()
        self._audit('users', user_id, 'password_reset', None, {'reset_by': changed_by}, changed_by)
        self.db.commit()
        self.db.refresh(user)
        return user

    def deactivate_user(self, user_id: str, changed_by: str) -> Optional[User]:
        return self.update_user(user_id, UserUpdate(is_active=False), changed_by)

    # =========================================================================
    # DOMAIN MANAGEMENT
    # =========================================================================

    def list_domains(self, include_inactive: bool = True) -> List[Domain]:
        q = self.db.query(Domain)
        if not include_inactive:
            q = q.filter(Domain.is_active == True)
        return q.order_by(Domain.seq_number).all()

    def update_domain(self, domain_id: str, data: DomainUpdate, user_id: str) -> Optional[Domain]:
        domain = self.db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            return None
        for field, val in data.model_dump(exclude_none=True, exclude={'change_reason'}).items():
            old = getattr(domain, field)
            setattr(domain, field, val)
            self._audit('domains', domain_id, field, old, val, user_id, data.change_reason)
        domain.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(domain)
        return domain

    # =========================================================================
    # ARTEFACT TYPES
    # =========================================================================

    def list_artefact_types(self) -> List[ArtefactType]:
        return self.db.query(ArtefactType).order_by(ArtefactType.label).all()

    def create_artefact_type(self, data: ArtefactTypeCreate, user_id: str) -> ArtefactType:
        obj = ArtefactType(**data.model_dump())
        self.db.add(obj)
        self.db.flush()
        self._audit('artefact_types', str(obj.id), 'created', None, data.model_dump(), user_id)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def update_artefact_type(self, artefact_type_id: str, data: ArtefactTypeUpdate, user_id: str) -> Optional[ArtefactType]:
        obj = self.db.query(ArtefactType).filter(ArtefactType.id == artefact_type_id).first()
        if not obj:
            return None
        for field, val in data.model_dump(exclude_none=True).items():
            old = getattr(obj, field)
            setattr(obj, field, val)
            self._audit('artefact_types', artefact_type_id, field, old, val, user_id)
        obj.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete_artefact_type(self, artefact_type_id: str, user_id: str) -> bool:
        obj = self.db.query(ArtefactType).filter(ArtefactType.id == artefact_type_id).first()
        if not obj:
            return False
        obj.is_active = False
        self._audit('artefact_types', artefact_type_id, 'is_active', True, False, user_id)
        self.db.commit()
        return True

    # =========================================================================
    # PTX GATES
    # =========================================================================

    def list_ptx_gates(self) -> List[PtxGate]:
        return self.db.query(PtxGate).order_by(PtxGate.sort_order).all()

    def create_ptx_gate(self, data: PtxGateCreate, user_id: str) -> PtxGate:
        obj = PtxGate(**data.model_dump())
        self.db.add(obj)
        self.db.flush()
        self._audit('ptx_gates', str(obj.id), 'created', None, data.model_dump(), user_id)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def update_ptx_gate(self, gate_id: str, data: PtxGateUpdate, user_id: str) -> Optional[PtxGate]:
        obj = self.db.query(PtxGate).filter(PtxGate.id == gate_id).first()
        if not obj:
            return None
        for field, val in data.model_dump(exclude_none=True).items():
            old = getattr(obj, field)
            setattr(obj, field, val)
            self._audit('ptx_gates', gate_id, field, old, val, user_id)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete_ptx_gate(self, gate_id: str, user_id: str) -> bool:
        obj = self.db.query(PtxGate).filter(PtxGate.id == gate_id).first()
        if not obj:
            return False
        obj.is_active = False
        self._audit('ptx_gates', gate_id, 'is_active', True, False, user_id)
        self.db.commit()
        return True

    # =========================================================================
    # ARCHITECTURE DISPOSITIONS
    # =========================================================================

    def list_dispositions(self) -> List[ArchitectureDisposition]:
        return self.db.query(ArchitectureDisposition).order_by(ArchitectureDisposition.sort_order).all()

    def create_disposition(self, data: DispositionCreate, user_id: str) -> ArchitectureDisposition:
        obj = ArchitectureDisposition(**data.model_dump())
        self.db.add(obj)
        self.db.flush()
        self._audit('architecture_dispositions', str(obj.id), 'created', None, data.model_dump(), user_id)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def update_disposition(self, disp_id: str, data: DispositionUpdate, user_id: str) -> Optional[ArchitectureDisposition]:
        obj = self.db.query(ArchitectureDisposition).filter(ArchitectureDisposition.id == disp_id).first()
        if not obj:
            return None
        for field, val in data.model_dump(exclude_none=True).items():
            old = getattr(obj, field)
            setattr(obj, field, val)
            self._audit('architecture_dispositions', disp_id, field, old, val, user_id)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete_disposition(self, disp_id: str, user_id: str) -> bool:
        obj = self.db.query(ArchitectureDisposition).filter(ArchitectureDisposition.id == disp_id).first()
        if not obj:
            return False
        obj.is_active = False
        self._audit('architecture_dispositions', disp_id, 'is_active', True, False, user_id)
        self.db.commit()
        return True

    # =========================================================================
    # EA PRINCIPLES
    # =========================================================================

    def list_ea_principles(self) -> List[EAPrinciple]:
        return self.db.query(EAPrinciple).order_by(EAPrinciple.principle_code).all()

    def create_ea_principle(self, data: EAPrincipleCreate, user_id: str) -> EAPrinciple:
        obj = EAPrinciple(**data.model_dump())
        self.db.add(obj)
        self.db.flush()
        self._audit('ea_principles', str(obj.id), 'created', None, data.model_dump(), user_id)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def update_ea_principle(self, principle_id: str, data: EAPrincipleUpdate, user_id: str) -> Optional[EAPrinciple]:
        obj = self.db.query(EAPrinciple).filter(EAPrinciple.id == principle_id).first()
        if not obj:
            return None
        for field, val in data.model_dump(exclude_none=True).items():
            old = getattr(obj, field, None)
            setattr(obj, field, val)
            self._audit('ea_principles', principle_id, field, old, val, user_id)
        obj.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete_ea_principle(self, principle_id: str, user_id: str) -> bool:
        obj = self.db.query(EAPrinciple).filter(EAPrinciple.id == principle_id).first()
        if not obj:
            return False
        obj.is_active = False
        self._audit('ea_principles', principle_id, 'is_active', True, False, user_id)
        self.db.commit()
        return True

    # =========================================================================
    # CHECKLIST SUBSECTIONS
    # =========================================================================

    def list_subsections(self, domain_id: Optional[str] = None) -> List[ChecklistSubsection]:
        q = self.db.query(ChecklistSubsection)
        if domain_id:
            q = q.filter(ChecklistSubsection.domain_id == domain_id)
        return q.order_by(ChecklistSubsection.sort_order).all()

    def create_subsection(self, data: ChecklistSubsectionCreate, user_id: str) -> ChecklistSubsection:
        obj = ChecklistSubsection(**data.model_dump())
        self.db.add(obj)
        self.db.flush()
        self._audit('checklist_subsections', str(obj.id), 'created', None, data.model_dump(), user_id)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def update_subsection(self, sub_id: str, data: ChecklistSubsectionUpdate, user_id: str) -> Optional[ChecklistSubsection]:
        obj = self.db.query(ChecklistSubsection).filter(ChecklistSubsection.id == sub_id).first()
        if not obj:
            return None
        for field, val in data.model_dump(exclude_none=True).items():
            old = getattr(obj, field)
            setattr(obj, field, val)
            self._audit('checklist_subsections', sub_id, field, old, val, user_id)
        obj.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete_subsection(self, sub_id: str, user_id: str) -> bool:
        obj = self.db.query(ChecklistSubsection).filter(ChecklistSubsection.id == sub_id).first()
        if not obj:
            return False
        obj.is_active = False
        self._audit('checklist_subsections', sub_id, 'is_active', True, False, user_id)
        self.db.commit()
        return True

    # =========================================================================
    # CHECKLIST QUESTIONS
    # =========================================================================

    def list_questions(self, subsection_id: Optional[str] = None) -> List[ChecklistQuestion]:
        q = self.db.query(ChecklistQuestion)
        if subsection_id:
            q = q.filter(ChecklistQuestion.subsection_id == subsection_id)
        return q.order_by(ChecklistQuestion.sort_order).all()

    def create_question(self, data: ChecklistQuestionCreate, user_id: str) -> ChecklistQuestion:
        obj = ChecklistQuestion(**data.model_dump())
        self.db.add(obj)
        self.db.flush()
        self._audit('checklist_questions', str(obj.id), 'created', None, data.model_dump(), user_id)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def update_question(self, q_id: str, data: ChecklistQuestionUpdate, user_id: str) -> Optional[ChecklistQuestion]:
        obj = self.db.query(ChecklistQuestion).filter(ChecklistQuestion.id == q_id).first()
        if not obj:
            return None
        for field, val in data.model_dump(exclude_none=True).items():
            old = getattr(obj, field)
            setattr(obj, field, val)
            self._audit('checklist_questions', q_id, field, old, val, user_id)
        obj.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete_question(self, q_id: str, user_id: str) -> bool:
        obj = self.db.query(ChecklistQuestion).filter(ChecklistQuestion.id == q_id).first()
        if not obj:
            return False
        obj.is_active = False
        self._audit('checklist_questions', q_id, 'is_active', True, False, user_id)
        self.db.commit()
        return True

    # =========================================================================
    # PROMPT TEMPLATES  (super_admin only)
    # =========================================================================

    def list_prompts(self) -> List[PromptTemplate]:
        """Return one active prompt per prompt_key (highest version)."""
        subq = (
            self.db.query(
                PromptTemplate.prompt_key,
                func.max(PromptTemplate.version).label('max_ver'),
            )
            .filter(PromptTemplate.is_active == True)
            .group_by(PromptTemplate.prompt_key)
            .subquery()
        )
        return (
            self.db.query(PromptTemplate)
            .join(subq, (PromptTemplate.prompt_key == subq.c.prompt_key) & (PromptTemplate.version == subq.c.max_ver))
            .filter(PromptTemplate.is_active == True)
            .order_by(PromptTemplate.prompt_key)
            .all()
        )

    def get_prompt_history(self, prompt_key: str) -> List[PromptTemplate]:
        return (
            self.db.query(PromptTemplate)
            .filter(PromptTemplate.prompt_key == prompt_key)
            .order_by(PromptTemplate.version.desc())
            .all()
        )

    def save_prompt(self, data: PromptTemplateCreate, user_id: str) -> PromptTemplate:
        latest = (
            self.db.query(PromptTemplate)
            .filter(PromptTemplate.prompt_key == data.prompt_key)
            .order_by(PromptTemplate.version.desc())
            .first()
        )
        next_version = (latest.version + 1) if latest else 1
        # Deactivate previous active version
        self.db.query(PromptTemplate).filter(
            PromptTemplate.prompt_key == data.prompt_key,
            PromptTemplate.is_active == True,
        ).update({'is_active': False})
        obj = PromptTemplate(
            prompt_key=data.prompt_key,
            prompt_type=data.prompt_type,
            domain_code=data.domain_code,
            version=next_version,
            content=data.content,
            is_active=True,
            notes=data.notes,
            created_by=UUID(user_id),
        )
        self.db.add(obj)
        self.db.flush()
        self._audit('prompt_templates', str(obj.id), 'saved', None, {'key': data.prompt_key, 'version': next_version}, user_id)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def revert_prompt(self, prompt_key: str, version: int, user_id: str) -> Optional[PromptTemplate]:
        target = (
            self.db.query(PromptTemplate)
            .filter(PromptTemplate.prompt_key == prompt_key, PromptTemplate.version == version)
            .first()
        )
        if not target:
            return None
        self.db.query(PromptTemplate).filter(
            PromptTemplate.prompt_key == prompt_key,
            PromptTemplate.is_active == True,
        ).update({'is_active': False})
        target.is_active = True
        self._audit('prompt_templates', str(target.id), 'reverted', None, {'version': version}, user_id)
        self.db.commit()
        self.db.refresh(target)
        return target

    # =========================================================================
    # KB DOCUMENTS  (super_admin only)
    # =========================================================================

    def list_kb_documents(self, include_inactive: bool = False) -> List[KbDocument]:
        q = self.db.query(KbDocument)
        if not include_inactive:
            q = q.filter(KbDocument.is_active == True)
        return q.order_by(KbDocument.uploaded_at.desc()).all()

    def create_kb_document(
        self,
        file_name: str,
        title: str,
        domain_codes: List[str],
        content: bytes,
        user_id: str,
    ) -> KbDocument:
        kb_dir = os.path.abspath(KB_DIR)
        os.makedirs(kb_dir, exist_ok=True)
        file_path = os.path.join(kb_dir, file_name)
        with open(file_path, 'wb') as f:
            f.write(content)
        content_hash = hashlib.md5(content).hexdigest()
        obj = KbDocument(
            file_name=file_name,
            title=title,
            domain_codes=domain_codes,
            file_path=file_path,
            file_size=len(content),
            content_hash=content_hash,
            is_active=True,
            uploaded_by=UUID(user_id),
        )
        self.db.add(obj)
        self.db.flush()
        self._audit('kb_documents', str(obj.id), 'uploaded', None, {'file_name': file_name, 'title': title}, user_id)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def update_kb_document(self, doc_id: str, data: KbDocumentUpdate, user_id: str) -> Optional[KbDocument]:
        obj = self.db.query(KbDocument).filter(KbDocument.id == doc_id).first()
        if not obj:
            return None
        for field, val in data.model_dump(exclude_none=True).items():
            old = getattr(obj, field)
            setattr(obj, field, val)
            self._audit('kb_documents', doc_id, field, old, val, user_id)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete_kb_document(self, doc_id: str, user_id: str) -> bool:
        obj = self.db.query(KbDocument).filter(KbDocument.id == doc_id).first()
        if not obj:
            return False
        obj.is_active = False
        self._audit('kb_documents', doc_id, 'is_active', True, False, user_id)
        self.db.commit()
        return True

    def scan_kb_directory(self, user_id: str) -> Dict[str, Any]:
        """Register KB files from disk that aren't yet in the DB."""
        kb_dir = os.path.abspath(KB_DIR)
        if not os.path.exists(kb_dir):
            return {'scanned': 0, 'registered': 0}
        registered_files = {doc.file_name for doc in self.db.query(KbDocument).all()}
        scanned = 0
        newly_registered = 0
        for fname in os.listdir(kb_dir):
            if not fname.endswith('.md'):
                continue
            scanned += 1
            if fname in registered_files:
                continue
            fpath = os.path.join(kb_dir, fname)
            with open(fpath, 'rb') as f:
                content = f.read()
            obj = KbDocument(
                file_name=fname,
                title=fname.replace('-', ' ').replace('_', ' ').replace('.md', '').title(),
                domain_codes=[],
                file_path=fpath,
                file_size=len(content),
                content_hash=hashlib.md5(content).hexdigest(),
                is_active=True,
                uploaded_by=UUID(user_id),
            )
            self.db.add(obj)
            newly_registered += 1
        self.db.commit()
        return {'scanned': scanned, 'registered': newly_registered}

    # =========================================================================
    # ANALYTICS
    # =========================================================================

    def get_analytics_summary(self) -> Dict[str, Any]:
        total = self.db.query(func.count(Review.id)).scalar() or 0
        pending = self.db.query(func.count(Review.id)).filter(
            Review.status.in_(['queued', 'submitted', 'analysing'])
        ).scalar() or 0
        approved = self.db.query(func.count(Review.id)).filter(Review.decision == 'approved').scalar() or 0
        rejected = self.db.query(func.count(Review.id)).filter(Review.decision == 'rejected').scalar() or 0
        deferred = self.db.query(func.count(Review.id)).filter(Review.decision == 'deferred').scalar() or 0

        from datetime import date
        first_of_month = date.today().replace(day=1)
        this_month = self.db.query(func.count(Review.id)).filter(
            func.date(Review.created_at) >= first_of_month
        ).scalar() or 0

        avg_score_row = self.db.query(func.avg(DomainScore.score)).scalar()
        avg_score = round(float(avg_score_row), 2) if avg_score_row else None
        approval_rate = round(approved / total * 100, 1) if total > 0 else None

        return {
            'total_reviews': total,
            'pending_reviews': pending,
            'approved_reviews': approved,
            'rejected_reviews': rejected,
            'deferred_reviews': deferred,
            'reviews_this_month': this_month,
            'avg_domain_score': avg_score,
            'approval_rate': approval_rate,
        }

    def get_domain_analytics(self) -> List[Dict[str, Any]]:
        domains = self.db.query(Domain).filter(Domain.is_active == True).order_by(Domain.seq_number).all()
        results = []
        for d in domains:
            avg = self.db.query(func.avg(DomainScore.score)).filter(DomainScore.domain == d.slug).scalar()
            count = self.db.query(func.count(DomainScore.id)).filter(DomainScore.domain == d.slug).scalar() or 0
            blockers = self.db.query(func.count(Blocker.id)).join(
                Review, Blocker.review_id == Review.id
            ).filter(Blocker.domain == d.slug.upper()[:3]).scalar() or 0
            results.append({
                'domain_slug': d.slug,
                'domain_name': d.name,
                'avg_score': round(float(avg), 2) if avg else None,
                'total_reviews': count,
                'blocker_count': blockers,
            })
        return results

    def get_recent_reviews(self, limit: int = 20) -> List[Review]:
        return (
            self.db.query(Review)
            .order_by(Review.created_at.desc())
            .limit(limit)
            .all()
        )
