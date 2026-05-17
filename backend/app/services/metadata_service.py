from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Dict, Any, Optional
from app.db.metadata_models import (
    SubmissionStep, Domain, DomainStep, ArtefactType, ArtefactTemplate,
    ChecklistSubsection, ChecklistQuestion, QuestionOption,
    EAPrinciple, PrincipleDomain, PtxGate, ArchitectureDisposition, FormField
)
from app.models.metadata import (
    Step, Domain as DomainModel, ArtefactType as ArtefactTypeModel,
    ArtefactTemplate as ArtefactTemplateModel, ChecklistSubsection as ChecklistSubsectionModel,
    ChecklistQuestion as ChecklistQuestionModel, QuestionOption as QuestionOptionModel,
    EAPrinciple as EAPrincipleModel, PtxGateSimple, ArchitectureDispositionSimple,
    EAPrincipleWithRelevance, FormField as FormFieldModel
)


class MetadataService:
    """Service for metadata operations"""

    def __init__(self, db: Session):
        self.db = db

    # ============================================================================
    # STEPS
    # ============================================================================
    def get_steps(self) -> List[Step]:
        """Get all submission steps ordered by step_order"""
        steps = self.db.query(SubmissionStep)\
            .filter(SubmissionStep.is_active == True)\
            .order_by(SubmissionStep.step_order)\
            .all()
        return [Step.model_validate(step) for step in steps]

    # ============================================================================
    # DOMAINS
    # ============================================================================
    def get_domains(self) -> List[DomainModel]:
        """Get all domains ordered by seq_number"""
        domains = self.db.query(Domain)\
            .filter(Domain.is_active == True)\
            .order_by(Domain.seq_number)\
            .all()
        return [DomainModel.model_validate(domain) for domain in domains]

    def get_domain_by_seq_number(self, seq_number: int) -> Optional[DomainModel]:
        """Get a domain by its sequence number"""
        domain = self.db.query(Domain)\
            .filter(Domain.seq_number == seq_number)\
            .filter(Domain.is_active == True)\
            .first()
        return DomainModel.model_validate(domain) if domain else None

    def get_domains_for_step(self, step_id: str) -> List[DomainModel]:
        """Get domains associated with a specific step"""
        domain_steps = self.db.query(DomainStep)\
            .join(Domain)\
            .filter(DomainStep.step_id == step_id)\
            .filter(DomainStep.is_active == True)\
            .all()
        return [DomainModel.model_validate(ds.domain) for ds in domain_steps if ds.domain]

    def get_step_to_domain_mapping(self) -> Dict[int, str]:
        """Get mapping of step_order to domain_slug"""
        steps = self.db.query(SubmissionStep)\
            .filter(SubmissionStep.is_active == True)\
            .order_by(SubmissionStep.step_order)\
            .all()
        
        domain_steps = self.db.query(DomainStep)\
            .join(Domain)\
            .filter(DomainStep.is_active == True)\
            .all()
        
        mapping: Dict[int, str] = {}
        for ds in domain_steps:
            step = next((s for s in steps if s.id == ds.step_id), None)
            if step and ds.domain:
                mapping[step.step_order] = ds.domain.slug
        
        return mapping

    # ============================================================================
    # ARTEFACT TYPES
    # ============================================================================
    def get_artefact_types(self) -> List[ArtefactTypeModel]:
        """Get all artefact types ordered by value"""
        artefact_types = self.db.query(ArtefactType)\
            .filter(ArtefactType.is_active == True)\
            .order_by(ArtefactType.value)\
            .all()
        return [ArtefactTypeModel.model_validate(at) for at in artefact_types]

    # ============================================================================
    # ARTEFACT TEMPLATES
    # ============================================================================
    def get_artefact_templates(self, domain_slug: str) -> List[ArtefactTemplateModel]:
        """Get artefact templates for a specific domain"""
        domain = self.db.query(Domain)\
            .filter(Domain.slug == domain_slug)\
            .first()
        
        if not domain:
            return []
        
        templates = self.db.query(ArtefactTemplate)\
            .join(ArtefactType)\
            .filter(ArtefactTemplate.domain_id == domain.id)\
            .filter(ArtefactTemplate.is_active == True)\
            .order_by(ArtefactTemplate.sort_order)\
            .all()
        
        result = []
        for template in templates:
            template_dict = ArtefactTemplateModel.model_validate(template).model_dump()
            template_dict['artefact_type'] = ArtefactTypeModel.model_validate(template.artefact_type) if template.artefact_type else None
            result.append(ArtefactTemplateModel(**template_dict))
        
        return result

    # ============================================================================
    # CHECKLIST SUBSECTIONS
    # ============================================================================
    def get_checklist_subsections(self, domain_slug: str) -> List[ChecklistSubsectionModel]:
        """Get checklist subsections for a specific domain with nested questions and options"""
        domain = self.db.query(Domain)\
            .filter(Domain.slug == domain_slug)\
            .first()
        
        if not domain:
            return []
        
        # Get subsections for the domain
        subsections = self.db.query(ChecklistSubsection)\
            .filter(ChecklistSubsection.domain_id == domain.id)\
            .filter(ChecklistSubsection.is_active == True)\
            .order_by(ChecklistSubsection.sort_order)\
            .all()
        
        subsection_ids = [s.id for s in subsections]
        
        # Get questions for these subsections
        questions = self.db.query(ChecklistQuestion)\
            .filter(ChecklistQuestion.subsection_id.in_(subsection_ids))\
            .filter(ChecklistQuestion.is_active == True)\
            .order_by(ChecklistQuestion.sort_order)\
            .all()
        
        question_ids = [q.id for q in questions]
        
        # Get all question options
        question_options = self.db.query(QuestionOption)\
            .filter(QuestionOption.question_id.in_(question_ids))\
            .filter(QuestionOption.is_active == True)\
            .order_by(QuestionOption.sort_order)\
            .all()
        
        # Map options to questions
        options_by_question: Dict[str, List[QuestionOptionModel]] = {}
        for option in question_options:
            if str(option.question_id) not in options_by_question:
                options_by_question[str(option.question_id)] = []
            options_by_question[str(option.question_id)].append(
                QuestionOptionModel.model_validate(option)
            )
        
        # Sort options for each question
        for question_id in options_by_question:
            options_by_question[question_id].sort(key=lambda x: x.sort_order)
        
        # Map questions to subsections
        questions_by_subsection: Dict[str, List[ChecklistQuestionModel]] = {}
        for question in questions:
            question_dict = ChecklistQuestionModel.model_validate(question).model_dump()
            question_dict['options'] = options_by_question.get(str(question.id), [])
            question_model = ChecklistQuestionModel(**question_dict)
            
            if str(question.subsection_id) not in questions_by_subsection:
                questions_by_subsection[str(question.subsection_id)] = []
            questions_by_subsection[str(question.subsection_id)].append(question_model)
        
        # Sort questions for each subsection
        for subsection_id in questions_by_subsection:
            questions_by_subsection[subsection_id].sort(key=lambda x: x.sort_order)
        
        # Build final result
        result = []
        for subsection in subsections:
            subsection_dict = ChecklistSubsectionModel.model_validate(subsection).model_dump()
            subsection_dict['questions'] = questions_by_subsection.get(str(subsection.id), [])
            result.append(ChecklistSubsectionModel(**subsection_dict))
        
        return result

    # ============================================================================
    # PTX GATES
    # ============================================================================
    def get_ptx_gates(self) -> List[PtxGateSimple]:
        """Get all PTX gates"""
        ptx_gates = self.db.query(PtxGate)\
            .filter(PtxGate.is_active == True)\
            .order_by(PtxGate.sort_order)\
            .all()
        return [
            PtxGateSimple(value=pg.value, label=pg.label)
            for pg in ptx_gates
        ]

    # ============================================================================
    # ARCHITECTURE DISPOSITIONS
    # ============================================================================
    def get_architecture_dispositions(self) -> List[ArchitectureDispositionSimple]:
        """Get all architecture dispositions"""
        dispositions = self.db.query(ArchitectureDisposition)\
            .filter(ArchitectureDisposition.is_active == True)\
            .order_by(ArchitectureDisposition.sort_order)\
            .all()
        return [
            ArchitectureDispositionSimple(value=ad.value, label=ad.label)
            for ad in dispositions
        ]

    # ============================================================================
    # EA PRINCIPLES
    # ============================================================================
    def get_ea_principles(self) -> List[EAPrincipleModel]:
        """Get all EA principles ordered by category and principle_code"""
        principles = self.db.query(EAPrinciple)\
            .filter(EAPrinciple.is_active == True)\
            .order_by(EAPrinciple.category, EAPrinciple.principle_code)\
            .all()
        return [EAPrincipleModel.model_validate(p) for p in principles]

    def get_ea_principles_for_domain(self, domain_slug: str) -> List[EAPrincipleWithRelevance]:
        """Get EA principles for a specific domain with relevance scores"""
        domain = self.db.query(Domain)\
            .filter(Domain.slug == domain_slug)\
            .first()
        
        if not domain:
            return []
        
        principle_domains = self.db.query(PrincipleDomain)\
            .join(EAPrinciple)\
            .filter(PrincipleDomain.domain_id == domain.id)\
            .filter(PrincipleDomain.relevance_score > 0)\
            .order_by(PrincipleDomain.relevance_score.desc())\
            .all()
        
        result = []
        for pd in principle_domains:
            principle_dict = EAPrincipleModel.model_validate(pd.principle).model_dump()
            principle_dict['relevance_score'] = pd.relevance_score
            result.append(EAPrincipleWithRelevance(**principle_dict))
        
        return result

    # ============================================================================
    # FORM FIELDS
    # ============================================================================
    def get_form_fields(self, step_id: str) -> List[FormFieldModel]:
        """Get form fields for a specific step"""
        form_fields = self.db.query(FormField)\
            .filter(FormField.step_id == step_id)\
            .filter(FormField.is_active == True)\
            .order_by(FormField.sort_order)\
            .all()
        return [FormFieldModel.model_validate(ff) for ff in form_fields]

    # ============================================================================
    # QUESTION OPTIONS
    # ============================================================================
    def get_question_options(self, question_id: str) -> List[QuestionOptionModel]:
        """Get question options for a specific question"""
        options = self.db.query(QuestionOption)\
            .filter(QuestionOption.question_id == question_id)\
            .filter(QuestionOption.is_active == True)\
            .order_by(QuestionOption.sort_order)\
            .all()
        return [QuestionOptionModel.model_validate(o) for o in options]

    def get_all_question_options(self) -> List[QuestionOptionModel]:
        """Get all question options"""
        options = self.db.query(QuestionOption)\
            .filter(QuestionOption.is_active == True)\
            .order_by(QuestionOption.sort_order)\
            .all()
        return [QuestionOptionModel.model_validate(o) for o in options]

    # ============================================================================
    # ALL METADATA
    # ============================================================================
    def get_all_metadata(self) -> Dict[str, Any]:
        """Get all metadata in a single call"""
        domains = self.get_domains()
        artefact_types = self.get_artefact_types()
        ptx_gates = self.get_ptx_gates()
        architecture_dispositions = self.get_architecture_dispositions()
        ea_principles = self.get_ea_principles()
        question_options = self.get_all_question_options()
        
        return {
            "domains": domains,
            "artefactTypes": artefact_types,
            "ptxGates": ptx_gates,
            "architectureDispositions": architecture_dispositions,
            "eaPrinciples": ea_principles,
            "questionOptions": question_options
        }
