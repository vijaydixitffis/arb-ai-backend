from sqlalchemy.orm import Session
from app.db.review_models import Review
from app.services.artefact_service import ArtefactService
from app.agents.enhanced_orchestrator import EnhancedARBOrchestrator
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import json


class ReviewService:
    """Service for review operations using database with multiple artefact support"""

    def __init__(self, db: Session):
        self.db = db
        self.artefact_service = ArtefactService(db)
        self.orchestrator = EnhancedARBOrchestrator(db)

    def get_all_reviews(self) -> List[Review]:
        """Get all reviews"""
        return self.db.query(Review).all()

    def get_review(self, review_id: str) -> Optional[Review]:
        """Get a specific review by ID"""
        try:
            return self.db.query(Review).filter(Review.id == uuid.UUID(review_id)).first()
        except ValueError:
            return None

    def get_reviews_by_user(self, user_id: str) -> List[Review]:
        """Get reviews by SA user ID"""
        try:
            return self.db.query(Review).filter(Review.sa_user_id == uuid.UUID(user_id)).all()
        except ValueError:
            return []

    def get_reviews_by_status(self, status: str) -> List[Review]:
        """Get reviews by status"""
        return self.db.query(Review).filter(Review.status == status).all()

    def create_review(self, review_data: dict) -> Review:
        """Create a new review (without artefacts - artefacts uploaded separately)"""
        # Handle form_data that might be sent at root level
        report_json = review_data.get('report_json', {})
        if not report_json:
            report_json = {}
        
        # If form_data exists at root level, store it in report_json.form_data
        if 'form_data' in review_data:
            report_json['form_data'] = review_data['form_data']
        else:
            # Check for individual project fields that might be at root level
            project_fields = ['problem_statement', 'stakeholders', 'business_drivers', 'target_business_outcomes', 'ptx_gate', 'architecture_disposition']
            form_data = report_json.get('form_data', {})
            
            for field in project_fields:
                if field in review_data and field not in form_data:
                    form_data[field] = review_data[field]
            
            if form_data:
                report_json['form_data'] = form_data
        
        review = Review(
            id=uuid.uuid4(),
            sa_user_id=uuid.UUID(review_data.get('sa_user_id')) if review_data.get('sa_user_id') else None,
            solution_name=review_data.get('solution_name'),
            scope_tags=review_data.get('scope_tags', []),
            status=self._STATUS_MAP.get(review_data.get('status', 'drafting'), review_data.get('status', 'drafting')),
            report_json=report_json
        )
        self.db.add(review)
        self.db.commit()
        self.db.refresh(review)
        return review

    # Frontend / legacy values that don't match the DB CHECK constraint
    _STATUS_MAP = {
        'submitted': 'queued',
        'draft':     'drafting',
        'pending':   'queued',
    }

    def update_review(self, review_id: str, review_data: dict) -> Optional[Review]:
        """Update an existing review"""
        try:
            review = self.db.query(Review).filter(Review.id == uuid.UUID(review_id)).first()
            if not review:
                return None

            if 'status' in review_data and review_data['status'] is not None:
                review_data = {**review_data,
                               'status': self._STATUS_MAP.get(review_data['status'],
                                                               review_data['status'])}

            for key, value in review_data.items():
                if key == 'form_data':
                    existing = review.report_json or {}
                    # Always merge form_data properly
                    if value is not None and value != {}:
                        # Merge new form_data with existing form_data
                        existing_form_data = existing.get("form_data", {})
                        merged_form_data = {**existing_form_data, **value}
                        review.report_json = {**existing, "form_data": merged_form_data}
                elif hasattr(review, key) and value is not None:
                    setattr(review, key, value)
            self.db.commit()
            self.db.refresh(review)
            return review
        except ValueError:
            return None

    async def submit_review(self, review_id: str) -> Optional[Review]:
        """Submit a review for ARB evaluation"""
        try:
            review = self.db.query(Review).filter(Review.id == uuid.UUID(review_id)).first()
            if not review:
                return None
            
            # Check if review has artefacts
            artefacts = await self.artefact_service.get_artefacts_by_review(str(review.id))
            if not artefacts:
                raise ValueError("Cannot submit review without artefacts")
            
            review.status = 'queued'
            review.submitted_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(review)
            return review
        except ValueError:
            return None

    async def run_review_evaluation(self, review_id: str) -> Dict[str, Any]:
        """Run ARB evaluation using enhanced orchestrator"""
        try:
            # Prepare checklist data
            checklist_data = await self.orchestrator.prepare_checklist_data(review_id)
            
            # Run the review
            result = await self.orchestrator.run_review(
                review_id=review_id,
                checklist_data=checklist_data
            )
            
            # Update review with results
            review = self.db.query(Review).filter(Review.id == uuid.UUID(review_id)).first()
            if review:
                review.status = 'reviewed'
                review.decision = result.get('decision')
                review.report_json = result
                review.tokens_used = result.get('total_tokens_used')
                review.reviewed_at = datetime.utcnow()
                
                # Debug logging for domain_payloads
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"[REVIEW_SERVICE] Saving result with domain_payloads: {'domain_payloads' in result}")
                if 'domain_payloads' in result:
                    logger.info(f"[REVIEW_SERVICE] domain_payloads count: {len(result['domain_payloads'])}")
                else:
                    logger.warning(f"[REVIEW_SERVICE] domain_payloads missing from result. Keys: {list(result.keys())}")
                
                self.db.commit()
                
                # Verify the save
                self.db.refresh(review)
                saved_keys = list(review.report_json.keys()) if review.report_json else []
                logger.info(f"[REVIEW_SERVICE] Saved report_json keys: {saved_keys}")
            
            return result
        except Exception as e:
            # Update review with error status
            review = self.db.query(Review).filter(Review.id == uuid.UUID(review_id)).first()
            if review:
                review.status = 'error'
                review.report_json = {"error": str(e)}
                self.db.commit()
            raise

    def approve_review(self, review_id: str, override_rationale: Optional[str] = None) -> Optional[Review]:
        """Approve a review (EA approval)"""
        try:
            review = self.db.query(Review).filter(Review.id == uuid.UUID(review_id)).first()
            if not review:
                return None
            
            review.status = 'approved'
            review.decision = 'approve'
            review.ea_override_notes = override_rationale
            review.ea_overridden_at = datetime.utcnow()
            review.reviewed_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(review)
            return review
        except ValueError:
            return None

    def override_review(self, review_id: str, decision: str, rationale: str) -> Optional[Review]:
        """Override agent recommendation (EA override)"""
        try:
            review = self.db.query(Review).filter(Review.id == uuid.UUID(review_id)).first()
            if not review:
                return None
            
            review.status = 'overridden'
            review.decision = decision
            review.ea_override_notes = rationale
            review.ea_overridden_at = datetime.utcnow()
            review.reviewed_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(review)
            return review
        except ValueError:
            return None

    async def get_review_summary(self, review_id: str) -> Dict[str, Any]:
        """Get comprehensive review summary including artefacts"""
        return await self.orchestrator.get_review_summary(review_id)

    def extract_scope_tags(self, review_data: Dict[str, Any]) -> List[str]:
        """Extract scope tags from review data (aligned with frontend logic)"""
        VALID_DOMAINS = [
            'solution', 'business', 'application', 'integration',
            'data', 'infrastructure', 'devsecops', 'nfr'
        ]
        
        scope_tags = set()
        
        # Extract from domain_data structure (new format)
        domain_data = review_data.get("domain_data", {})
        for domain_slug, domain_info in domain_data.items():
            # Validate domain name
            if domain_slug not in VALID_DOMAINS:
                continue
                
            # Check if domain has meaningful data
            if domain_info:
                has_checklist = domain_info.get("checklist") and len(domain_info["checklist"]) > 0
                has_evidence = domain_info.get("evidence") and len(domain_info["evidence"]) > 0
                has_valid_answers = has_checklist and any(
                    answer and answer in ['compliant', 'non_compliant', 'partial', 'na']
                    for answer in domain_info["checklist"].values()
                )
                
                if has_checklist or has_evidence or has_valid_answers:
                    scope_tags.add(domain_slug)
        
        # Extract from legacy checklist/evidence fields (backward compatibility)
        for key, value in review_data.items():
            if key.endswith('_checklist') or key.endswith('_evidence'):
                domain_slug = key.replace('_checklist', '').replace('_evidence', '')
                
                if domain_slug in VALID_DOMAINS and value and len(value) > 0:
                    if key.endswith('_checklist'):
                        # Validate that we have actual compliance answers
                        has_valid_answers = any(
                            answer and answer in ['compliant', 'non_compliant', 'partial', 'na']
                            for answer in value.values()
                        )
                        if has_valid_answers:
                            scope_tags.add(domain_slug)
                    else:
                        # Evidence fields count if they have content
                        scope_tags.add(domain_slug)
        
        # Special handling for NFR criteria
        nfr_criteria = review_data.get("nfr_criteria", [])
        if nfr_criteria and len(nfr_criteria) > 0:
            has_valid_criteria = any(
                criterion.get("category") and criterion.get("criteria") and criterion.get("target_value")
                for criterion in nfr_criteria
            )
            if has_valid_criteria:
                scope_tags.add("nfr")
        
        # Extract from legacy scope_tags field if present
        if "scope_tags" in review_data:
            for tag in review_data["scope_tags"]:
                if tag in VALID_DOMAINS:
                    scope_tags.add(tag)
        
        # Ensure at least one tag exists (default to 'solution')
        if len(scope_tags) == 0:
            scope_tags.add("solution")
        
        # Return sorted list for consistency
        return sorted(list(scope_tags))
