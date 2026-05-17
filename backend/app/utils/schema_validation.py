"""
Backend ARB Schema Validation Utility
Mirrors frontend validation for dual-layer protection
"""

from typing import Dict, List, Any, Optional, Tuple
from pydantic import BaseModel, ValidationError, validator
import re
import logging

logger = logging.getLogger(__name__)

class NFRCriterion(BaseModel):
    """NFR Criterion validation model"""
    id: Optional[str] = None
    category: str
    criteria: str
    target_value: str
    actual_value: Optional[str] = None
    score: int
    evidence: Optional[str] = None
    
    @validator('score')
    def validate_score(cls, v):
        if not isinstance(v, int) or v < 0 or v > 10:
            raise ValueError('Score must be an integer between 0 and 10')
        return v
    
    @validator('category')
    def validate_category(cls, v):
        valid_categories = [
            'Performance', 'Scalability', 'Availability', 'Security',
            'Reliability', 'Maintainability', 'Usability', 'Compliance'
        ]
        if v not in valid_categories:
            logger.warning(f"Unknown NFR category: {v}")
        return v

class DomainData(BaseModel):
    """Domain data validation model"""
    checklist: Dict[str, str] = {}
    evidence: Dict[str, str] = {}
    
    @validator('checklist')
    def validate_checklist_answers(cls, v):
        valid_answers = ['compliant', 'non_compliant', 'partial', 'na']
        for question_code, answer in v.items():
            if answer not in valid_answers:
                raise ValueError(f'Invalid compliance answer "{answer}" for question {question_code}')
        return v

class FormData(BaseModel):
    """Form data validation model"""
    reviewId: Optional[str] = None
    solution_name: Optional[str] = None
    scope_tags: List[str] = []
    project_name: str
    problem_statement: str
    stakeholders: List[str] = []
    business_drivers: List[str] = []
    growth_plans: Optional[str] = None
    domain_data: Dict[str, DomainData] = {}
    nfr_criteria: List[NFRCriterion] = []
    
    @validator('reviewId')
    def validate_review_id(cls, v):
        if v and v != '':
            uuid_pattern = re.compile(
                r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
                re.IGNORECASE
            )
            if not uuid_pattern.match(v):
                raise ValueError('ReviewId must be a valid UUID or empty string')
        return v
    
    @validator('scope_tags')
    def validate_scope_tags(cls, v):
        valid_domains = [
            'solution', 'business', 'application', 'integration',
            'data', 'infrastructure', 'devsecops', 'nfr'
        ]
        for tag in v:
            if tag not in valid_domains:
                logger.warning(f"Invalid scope tag: {tag}")
        return v

class ValidationResult:
    """Validation result container"""
    def __init__(self, is_valid: bool, errors: List[str], warnings: List[str]):
        self.is_valid = is_valid
        self.errors = errors
        self.warnings = warnings
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings
        }

def validate_arb_form_data(form_data: Dict[str, Any], is_draft: bool = True) -> ValidationResult:
    """
    Validate ARB form data against schema requirements
    Mirrors frontend validation logic
    is_draft: If True, allows empty form data for browsing; if False, enforces all requirements
    """
    errors = []
    warnings = []
    
    try:
        # Use Pydantic for structural validation
        validated_data = FormData(**form_data)
        
        # For drafts, only validate structure, not required fields
        if not is_draft:
            # Required fields validation for submissions
            if not validated_data.project_name or not validated_data.project_name.strip():
                errors.append("Project name is required")
            
            if not validated_data.problem_statement or not validated_data.problem_statement.strip():
                errors.append("Problem statement is required")
            
            if not validated_data.stakeholders or len(validated_data.stakeholders) == 0:
                errors.append("At least one stakeholder is required")
            
            if not validated_data.business_drivers or len(validated_data.business_drivers) == 0:
                errors.append("At least one business driver is required")
            
            # Domain data is no longer required - only selected domains (scope_tags) matter
            pass
        else:
            # For drafts, only warn about missing data but don't error
            if not validated_data.project_name or not validated_data.project_name.strip():
                warnings.append("Project name is empty")
            
            if not validated_data.problem_statement or not validated_data.problem_statement.strip():
                warnings.append("Problem statement is empty")
            
            if not validated_data.stakeholders or len(validated_data.stakeholders) == 0:
                warnings.append("No stakeholders specified")
            
            if not validated_data.business_drivers or len(validated_data.business_drivers) == 0:
                warnings.append("No business drivers specified")
        
        # NFR criteria validation (always a warning, never an error)
        if not validated_data.nfr_criteria or len(validated_data.nfr_criteria) == 0:
            warnings.append("No NFR criteria defined - consider adding quantitative measures")
        
        # Domain data validation - checklists are OPTIONAL in +EARR flow
        valid_domains = [
            'solution', 'business', 'application', 'integration',
            'data', 'infrastructure', 'devsecops', 'nfr'
        ]
        
        domains_with_checklist = []
        for domain_slug, domain_info in validated_data.domain_data.items():
            if domain_slug not in valid_domains:
                warnings.append(f"Unknown domain '{domain_slug}' found in domain_data")
                continue
            
            has_checklist = domain_info.checklist and len(domain_info.checklist) > 0
            if has_checklist:
                domains_with_checklist.append(domain_slug)
        
        # Checklists are optional - just informational
        if len(domains_with_checklist) == 0:
            warnings.append("No domain checklists completed - checklists are optional but recommended")
        
        # Cross-validation warnings
        if validated_data.nfr_criteria and len(validated_data.nfr_criteria) > 0:
            has_valid_criteria = any(
                criterion.category and criterion.criteria and criterion.target_value
                for criterion in validated_data.nfr_criteria
            )
            if not has_valid_criteria:
                warnings.append("NFR criteria exist but none are complete")
        
        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)
        
    except ValidationError as e:
        # Convert Pydantic validation errors to our format
        pydantic_errors = []
        for error in e.errors():
            field_path = " -> ".join(str(loc) for loc in error["loc"])
            pydantic_errors.append(f"{field_path}: {error['msg']}")
        
        return ValidationResult(is_valid=False, errors=pydantic_errors, warnings=warnings)
    except Exception as e:
        logger.error(f"Unexpected validation error: {e}")
        return ValidationResult(
            is_valid=False, 
            errors=[f"Validation system error: {str(e)}"], 
            warnings=[]
        )

def validate_submission_completeness(form_data: Dict[str, Any], artefacts: Dict[str, List[Any]] = None, is_draft: bool = True) -> ValidationResult:
    """
    Validate submission completeness including artifacts
    is_draft: If True, allows empty form data for browsing; if False, enforces all requirements
    
    New +EARR requirements:
    1. User selects only domains needed (scope_tags) - not all mandatory
    2. Checklists are optional for selected domains
    3. At least one artifact per SELECTED domain (not total across all domains)
    """
    base_validation = validate_arb_form_data(form_data, is_draft=is_draft)
    errors = list(base_validation.errors)
    warnings = list(base_validation.warnings)
    
    # Get selected domains from scope_tags
    scope_tags = form_data.get("scope_tags", [])
    selected_domains = set(scope_tags) if scope_tags else set()
    
    if not is_draft:
        # NEW: At least one domain must be selected
        if not selected_domains:
            errors.append("At least one domain must be selected")
        
        # NEW: Check each SELECTED domain has at least one artifact
        if artefacts:
            for domain in selected_domains:
                domain_artefacts = artefacts.get(domain, [])
                if not domain_artefacts or len(domain_artefacts) == 0:
                    errors.append(f"At least one artifact must be uploaded for selected domain: {domain}")
        else:
            # If no artefacts dict at all, all selected domains are missing artefacts
            for domain in selected_domains:
                errors.append(f"At least one artifact must be uploaded for selected domain: {domain}")
        
        # Ensure solution_name is set
        solution_name = form_data.get("solution_name")
        if not solution_name or not solution_name.strip():
            errors.append("Solution name is required")
    else:
        # For drafts, just warn about missing artifacts and scope tags
        if not selected_domains:
            warnings.append("No domains selected - please select at least one domain")
        
        if artefacts:
            for domain in selected_domains:
                domain_artefacts = artefacts.get(domain, [])
                if not domain_artefacts or len(domain_artefacts) == 0:
                    warnings.append(f"No artifacts uploaded yet for domain: {domain}")
        else:
            for domain in selected_domains:
                warnings.append(f"No artifacts uploaded yet for domain: {domain}")
        
        solution_name = form_data.get("solution_name")
        if not solution_name or not solution_name.strip():
            warnings.append("Solution name not set")
    
    return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

def get_validation_summary(validation: ValidationResult) -> str:
    """Generate human-readable validation summary"""
    if validation.is_valid and len(validation.warnings) == 0:
        return "✅ Form is valid and ready for submission"
    
    summary_parts = []
    
    if len(validation.errors) > 0:
        summary_parts.append(f"❌ {len(validation.errors)} error(s) must be fixed:")
        for error in validation.errors:
            summary_parts.append(f"  • {error}")
    
    if len(validation.warnings) > 0:
        summary_parts.append(f"\n⚠️ {len(validation.warnings)} warning(s) to consider:")
        for warning in validation.warnings:
            summary_parts.append(f"  • {warning}")
    
    return "\n".join(summary_parts)

def validate_review_data_structure(review_data: Dict[str, Any]) -> ValidationResult:
    """
    Validate the overall review data structure
    Used in API endpoints for additional validation
    """
    errors = []
    warnings = []
    
    # Check required top-level fields
    required_fields = ['sa_user_id', 'solution_name', 'scope_tags', 'status']
    for field in required_fields:
        if field not in review_data:
            errors.append(f"Missing required field: {field}")
    
    # Validate status
    valid_statuses = [
        'drafting', 'queued', 'analysing', 'review_ready',
        'ea_reviewing', 'returned', 'approved', 'conditionally_approved',
        'deferred', 'rejected', 'closed',
        # legacy aliases accepted during transition
        'draft', 'pending', 'submitted', 'in_review', 'ea_review', 'rework',
    ]
    status = review_data.get('status')
    if status and status not in valid_statuses:
        errors.append(f"Invalid status: {status}. Valid statuses: {', '.join(valid_statuses)}")
    
    # Validate scope tags - at least one domain should be selected for +EARR
    scope_tags = review_data.get('scope_tags', [])
    if scope_tags and not isinstance(scope_tags, list):
        errors.append("Scope tags must be an array")
    elif not scope_tags:
        warnings.append("No domains selected - at least one domain should be selected for +EARR")
    
    # Validate report_json if present - use relaxed validation for +EARR
    report_json = review_data.get('report_json')
    if report_json and isinstance(report_json, dict):
        form_data = report_json.get('form_data')
        if form_data:
            # Use draft validation (warnings only) for structure validation
            form_validation = validate_arb_form_data(form_data, is_draft=True)
            warnings.extend(form_validation.warnings)
    
    return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)
