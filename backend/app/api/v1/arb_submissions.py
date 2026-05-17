from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Header
from typing import List, Optional
from app.models.arb_submission import ARBSubmission, DomainSection, ChecklistItem
from datetime import datetime
from app.core.security import decode_access_token

router = APIRouter()

# In-memory storage for demo (replace with database in production)
submissions_db = {}

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

@router.get("")
async def get_submissions(current_user: str = Depends(get_current_user)):
    """Get all ARB submissions"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return list(submissions_db.values())

@router.get("/{submission_id}")
async def get_submission(submission_id: str, current_user: str = Depends(get_current_user)):
    """Get a specific ARB submission"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if submission_id not in submissions_db:
        raise HTTPException(status_code=404, detail="Submission not found")
    return submissions_db[submission_id]

@router.post("")
async def create_submission(submission: ARBSubmission, current_user: str = Depends(get_current_user)):
    """Create a new ARB submission"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    submission.id = f"arb-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    submission.created_date = datetime.now()
    submission.overall_progress = calculate_progress(submission)
    submissions_db[submission.id] = submission
    return submission

@router.put("/{submission_id}")
async def update_submission(submission_id: str, submission: ARBSubmission, current_user: str = Depends(get_current_user)):
    """Update an existing ARB submission"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if submission_id not in submissions_db:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    submission.id = submission_id
    submission.overall_progress = calculate_progress(submission)
    submissions_db[submission_id] = submission
    return submission

@router.post("/{submission_id}/submit")
async def submit_submission(submission_id: str, current_user: str = Depends(get_current_user)):
    """Submit ARB submission for review"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if submission_id not in submissions_db:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    submission = submissions_db[submission_id]
    submission.status = "submitted"
    submission.submitted_date = datetime.now()
    return {"message": "Submission submitted successfully", "submission_id": submission_id}

@router.post("/{submission_id}/artefacts")
async def upload_artefact(submission_id: str, file: UploadFile = File(...), current_user: str = Depends(get_current_user)):
    """Upload an artefact for a submission"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if submission_id not in submissions_db:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    # Generate system label based on file type
    file_type = file.content_type or "unknown"
    system_label = generate_system_label(file.filename, file_type)
    
    # In production, save file to storage and return path
    return {
        "artefact_id": f"art-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "file_name": file.filename,
        "file_type": file_type,
        "system_label": system_label,
        "upload_date": datetime.now()
    }

@router.post("/{submission_id}/integration-catalogue")
async def upload_integration_catalogue(submission_id: str, file: UploadFile = File(...), current_user: str = Depends(get_current_user)):
    """Upload integration catalogue (Excel/CSV)"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if submission_id not in submissions_db:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    # In production, parse Excel/CSV and return structured data
    return {
        "message": "Integration catalogue uploaded successfully",
        "file_name": file.filename
    }

def calculate_progress(submission: ARBSubmission) -> float:
    """Calculate overall progress percentage"""
    sections = [
        submission.application_architecture,
        submission.integration_architecture,
        submission.data_architecture,
        submission.security_architecture,
        submission.infrastructure_architecture,
        submission.devsecops
    ]
    
    completed_sections = sum(1 for section in sections if section is not None)
    total_sections = len(sections)
    
    if total_sections == 0:
        return 0.0
    
    return (completed_sections / total_sections) * 100

def generate_system_label(filename: str, file_type: str) -> str:
    """Generate a system label for an artefact"""
    label_map = {
        "application/pdf": "PDF Document",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word Document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel Spreadsheet",
        "image/png": "PNG Image",
        "image/jpeg": "JPEG Image",
        "image/svg+xml": "SVG Diagram"
    }
    
    base_label = label_map.get(file_type, "Unknown File Type")
    
    # Add descriptive prefix based on filename
    filename_lower = filename.lower()
    if "architecture" in filename_lower:
        return f"Architecture - {base_label}"
    elif "hld" in filename_lower:
        return f"HLD Document - {base_label}"
    elif "design" in filename_lower:
        return f"Design Document - {base_label}"
    elif "security" in filename_lower:
        return f"Security Document - {base_label}"
    elif "data" in filename_lower:
        return f"Data Document - {base_label}"
    else:
        return f"General Artefact - {base_label}"
