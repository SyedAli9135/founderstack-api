from sqlalchemy import Column, String, Boolean, ForeignKey, Integer, Float, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
from sqlalchemy.orm import relationship
from .base import Base

class Organization(Base):
    """Represents a tenant (company/solo founder) in the platform with strict RLS isolation."""
    __tablename__ = 'organizations'
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    clerk_org_id = Column(String(255), unique=True, nullable=False)
    
    active_api_key_id = Column(UUID(as_uuid=True))
    llm_provider = Column(String(50), default='anthropic')
    
    plan_tier = Column(String(50), default='starter')
    max_agents = Column(Integer, default=3)
    max_workflows = Column(Integer, default=5)
    max_rag_storage_gb = Column(Integer, default=5)
    max_mcp_integrations = Column(Integer, default=3)
    
    stripe_customer_id = Column(String(255))
    stripe_subscription_id = Column(String(255))
    subscription_status = Column(String(50), default='trialing')
    trial_ends_at = Column(DateTime(timezone=True))
    
    settings = Column(JSONB, default=dict)
    onboarding_completed = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

class User(Base):
    """Represents a human user belonging to an Organization, linked to Clerk authentication."""
    __tablename__ = 'users'
    org_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    clerk_user_id = Column(String(255), unique=True, nullable=False)
    email = Column(String(320), nullable=False)
    full_name = Column(String(255))
    avatar_url = Column(String)
    role = Column(String(50), nullable=False, default='member')
    can_manage_api_keys = Column(Boolean, default=False)
    can_manage_integrations = Column(Boolean, default=False)
    can_approve_workflows = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime(timezone=True))

class Session(Base):
    """Tracks active user login sessions matching Clerk's session state."""
    __tablename__ = 'sessions'
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    org_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    clerk_session_id = Column(String(255), unique=True)
    ip_address = Column(INET)
    user_agent = Column(String)
    expires_at = Column(DateTime(timezone=True), nullable=False)
