from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_BASE_URL: str = "http://localhost:8000"
    
    # DB
    DATABASE_URL: str
    DATABASE_POOL_SIZE: int = 20
    
    # Auth
    CLERK_SECRET_KEY: str = ""
    CLERK_PUBLISHABLE_KEY: str = ""
    CLERK_WEBHOOK_SECRET: str = ""
    
    # LLM / AI
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX_RAG: str = "founderstack-rag"
    PINECONE_INDEX_TOOLS: str = "founderstack-tools"
    
    UPSTASH_REDIS_URL: str = ""
    UPSTASH_REDIS_TOKEN: str = ""
    
    NANGO_SECRET_KEY: str = ""
    COHERE_API_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    
    class Config:
        env_file = ".env"

settings = Settings()
