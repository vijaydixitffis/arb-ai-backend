from sqlalchemy.orm import Session
from app.db.user_models import User
from app.core.security import verify_password, get_password_hash
from typing import Optional


class AuthService:
    """Service for authentication operations using database users table"""

    def __init__(self, db: Session):
        self.db = db

    def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """
        Authenticate a user by email and password
        Returns User object if authentication succeeds, None otherwise
        """
        user = self.db.query(User).filter(User.email == email).first()
        
        if not user:
            return None
        
        # For development, handle both plain text and hashed passwords
        try:
            if not verify_password(password, user.user_password):
                return None
        except Exception:
            # If password verification fails (e.g., plain text), try direct comparison
            if password != user.user_password:
                return None
        
        return user

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get a user by email"""
        return self.db.query(User).filter(User.email == email).first()

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get a user by ID"""
        return self.db.query(User).filter(User.id == user_id).first()

    def create_user(self, email: str, password: str, role: str = 'sa') -> User:
        """
        Create a new user
        Returns the created User object
        """
        hashed_password = get_password_hash(password)
        user = User(
            email=email,
            user_password=hashed_password,
            role=role
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_user_password(self, user_id: str, new_password: str) -> Optional[User]:
        """Update a user's password"""
        user = self.get_user_by_id(user_id)
        if not user:
            return None
        
        user.user_password = get_password_hash(new_password)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_user_role(self, user_id: str, new_role: str) -> Optional[User]:
        """Update a user's role"""
        user = self.get_user_by_id(user_id)
        if not user:
            return None
        
        user.role = new_role
        self.db.commit()
        self.db.refresh(user)
        return user
