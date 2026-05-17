from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.models.user import UserLogin, Token
from app.core.security import create_access_token
from app.services.auth_service import AuthService
from app.core.database import get_db

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    auth_service = AuthService(db)
    user = auth_service.authenticate_user(form_data.username, form_data.password)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if hasattr(user, 'is_active') and not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # Stamp last login
    if hasattr(user, 'last_login_at'):
        user.last_login_at = datetime.utcnow()
        db.commit()

    access_token = create_access_token(data={"sub": str(user.id), "role": user.role})

    return Token(
        access_token=access_token,
        token_type="bearer",
        user={
            "id": str(user.id),
            "email": user.email,
            "name": user.email.split('@')[0],
            "role": user.role
        }
    )

@router.get("/demo-users")
async def get_demo_users(db: Session = Depends(get_db)):
    """Return information about default users in the database"""
    auth_service = AuthService(db)
    
    users = []
    for email in ['sa_user@mail.com', 'ea_user@mail.com', 'admin@mail.com']:
        user = auth_service.get_user_by_email(email)
        if user:
            users.append({
                "email": user.email,
                "password": "password123",  # Default password from migration
                "role": user.role
            })
    
    return {"users": users}
