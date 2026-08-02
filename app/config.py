from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_BASE_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"

    # DB
    DATABASE_URL: str
    DATABASE_POOL_SIZE: int = 20

    # Auth
    CLERK_SECRET_KEY: SecretStr
    CLERK_PUBLISHABLE_KEY: str
    CLERK_WEBHOOK_SECRET: SecretStr

    # LocalStack
    LOCALSTACK_AUTH_TOKEN: SecretStr

    # OAuth
    SLACK_CLIENT_ID: str = ""
    SLACK_CLIENT_SECRET: SecretStr = SecretStr("")

    NOTION_CLIENT_ID: str = ""
    NOTION_CLIENT_SECRET: SecretStr = SecretStr("")

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: SecretStr = SecretStr("")

    TWITTER_CLIENT_ID: str = ""
    TWITTER_SECRET_KEY: SecretStr = SecretStr("")

    LINKEDIN_CLIENT_ID: str = ""
    LINKEDIN_CLIENT_SECRET: SecretStr = SecretStr("")

    # LLM / AI
    PINECONE_API_KEY: SecretStr
    PINECONE_INDEX_RAG: str = "founderstack-rag"
    PINECONE_INDEX_TOOLS: str = "founderstack-tools"

    UPSTASH_REDIS_URL: str = ""
    UPSTASH_REDIS_TOKEN: SecretStr = SecretStr("")

    NANGO_SECRET_KEY: SecretStr = SecretStr("")
    COHERE_API_KEY: SecretStr = SecretStr("")
    AWS_REGION: str = "us-east-1"

    # Document storage (S3 / LocalStack)
    S3_BUCKET_DOCUMENTS: str = "founderstack-documents"
    AWS_ACCESS_KEY_ID: str = "test"
    AWS_SECRET_ACCESS_KEY: SecretStr = SecretStr("test")
    # Set to http://localhost:4566 for local LocalStack; leave empty to hit real AWS
    AWS_S3_ENDPOINT_URL: str = ""

    # Security
    ENCRYPTION_KEY: SecretStr
    OAUTH_STATE_SECRET: SecretStr
    ANTHROPIC_API_KEY_MOCK_PREFIX: str = "sk-ant-test-"

    class Config:
        env_file = ".env"


settings = Settings()
