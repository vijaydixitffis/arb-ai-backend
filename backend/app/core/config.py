from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # API Configuration
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "ARB AI Agent"
    
    # Backend Configuration - ONLY PostgreSQL for Python backend
    BACKEND_TYPE: str = "postgresql"
    
    # OpenAI Configuration
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-large"
    
    # Gemini Configuration
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-2.5-flash-lite"
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"

    # OpenRouter Configuration (OpenAI-compatible, supports free/paid models)
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_MODEL: str = "openai/gpt-oss-120b:free"

    # LLM Provider Selection
    LLM_PROVIDER: str = "gemini"  # Options: "openai", "gemini", "openrouter"

    # Mock LLM — when true, bypasses all LLM calls and uses the Bank EDMS fixture
    USE_MOCK_LLM: bool = False

    # LLM call parameters — synthesis step
    LLM_TEMPERATURE: float = 0.3
    LLM_MAX_TOKENS: int = 4096

    # LLM call parameters — domain agents
    DOMAIN_LLM_TEMPERATURE: float = 0.5
    DOMAIN_LLM_MAX_TOKENS: int = 16384

    # Agent retry behaviour
    AGENT_MAX_RETRIES: int = 2           # total attempts (1 initial + N-1 retries)
    AGENT_RETRY_DELAY_S: float = 10.0   # seconds between retry attempts

    # Agent pacing
    INTER_DOMAIN_DELAY_S: float = 0.5   # seconds between sequential domain calls

    # KB retrieval limits (base values, scaled by content_scale at runtime)
    KB_CHUNK_LIMIT: int = 15
    KB_DOMAIN_RESULTS: int = 8
    KB_GENERAL_RESULTS: int = 4
    KB_CONTENT_SCALE: float = 1.0       # default content scale passed to domain agent
    CONTENT_SCALE_ON_RETRY: float = 0.75  # content scale applied on retry attempt

    # PostgreSQL Configuration
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/arb_ai_agent"
    
    # JWT Configuration
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # File Upload Configuration
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50MB
    ALLOWED_FILE_TYPES: list = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "image/png",
        "image/jpeg",
        "image/svg+xml"
    ]
    
    class Config:
        env_file = ".env"
        case_sensitive = True

    @property
    def is_supabase(self) -> bool:
        """Check if Supabase backend is configured"""
        return self.BACKEND_TYPE.lower() == "supabase"
    
    @property
    def is_supabase_storage(self) -> bool:
        """Check if Supabase storage is configured"""
        return self.STORAGE_TYPE.lower() == "supabase"

settings = Settings()
