from sqlalchemy import Column, String, Boolean, ForeignKey, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from .base import Base

class MCPConnection(Base):
    """An active OAuth or API key integration authorizing an agent to use external tools."""
    __tablename__ = 'mcp_connections'
    org_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    service_name = Column(String(100), nullable=False)
    display_name = Column(String(255), nullable=True)
    credential_provider = Column(String(50), default='manual')
    encrypted_credentials = Column(String, nullable=True)  # JSON blob of access/refresh tokens
    oauth_status = Column(String(50), default='pending')
    oauth_scopes = Column(JSONB, default='[]')
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

class ApiKeyRegistry(Base):
    """Securely stores Bring Your Own Key (BYOK) vendor tokens (like Anthropic keys) encrypted at rest."""
    __tablename__ = 'api_key_registry'
    org_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    provider = Column(String(50), nullable=False)
    key_prefix = Column(String(20), nullable=False)
    encrypted_key = Column(String(500), nullable=False)
    kms_key_id = Column(String(255), nullable=False)
    is_valid = Column(Boolean, default=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
