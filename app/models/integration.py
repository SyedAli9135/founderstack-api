from sqlalchemy import Column, String, Boolean, ForeignKey, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from .base import Base

class MCPConnection(Base):
    """An active OAuth integration (via Nango) authorizing an agent to use external tools (e.g. Stripe, Notion)."""
    __tablename__ = 'mcp_connections'
    org_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    service_name = Column(String(100), nullable=False)
    nango_connection_id = Column(String(255), unique=True, nullable=False)
    oauth_status = Column(String(50), default='active')
    sync_status = Column(String(50), default='healthy')
    allowed_tools = Column(JSONB)
    is_active = Column(Boolean, default=True)

class ApiKeyRegistry(Base):
    """Securely stores Bring Your Own Key (BYOK) vendor tokens (like Anthropic keys) encrypted at rest."""
    __tablename__ = 'api_key_registry'
    org_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    provider = Column(String(50), nullable=False)
    key_prefix = Column(String(20), nullable=False)
    encrypted_key = Column(String(500), nullable=False)
    kms_key_id = Column(String(255), nullable=False)
    is_valid = Column(Boolean, default=True)
