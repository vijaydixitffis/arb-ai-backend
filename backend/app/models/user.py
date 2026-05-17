from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from app.core.security import get_password_hash

class UserRole(str, Enum):
    SOLUTION_ARCHITECT = "solution_architect"
    ENTERPRISE_ARCHITECT = "enterprise_architect"
    ARB_ADMIN = "arb_admin"
    SUPER_ADMIN = "super_admin"

class User(BaseModel):
    id: str
    email: str
    name: str
    role: UserRole
    
class UserInDB(User):
    hashed_password: str

class UserLogin(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user: User

# Demo users
DEMO_USERS = {
    "sa@arb.demo": {
        "id": "1",
        "email": "sa@arb.demo",
        "name": "Solution Architect",
        "role": UserRole.SOLUTION_ARCHITECT,
        "hashed_password": get_password_hash("demo1234")
    },
    "ea@arb.demo": {
        "id": "2",
        "email": "ea@arb.demo",
        "name": "Enterprise Architect",
        "role": UserRole.ENTERPRISE_ARCHITECT,
        "hashed_password": get_password_hash("demo1234")
    },
    "admin@arb.demo": {
        "id": "3",
        "email": "admin@arb.demo",
        "name": "ARB Admin",
        "role": UserRole.ARB_ADMIN,
        "hashed_password": get_password_hash("demo1234")
    }
}
