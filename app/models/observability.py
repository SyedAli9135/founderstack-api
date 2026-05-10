from sqlalchemy import Column, String, Boolean, ForeignKey, Integer, Float, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from .base import Base

class AuditLog(Base):
    """Append-only, immutable record tracking critical system actions for enterprise compliance audits."""
    __tablename__ = 'audit_logs'
    org_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    actor_id = Column(UUID(as_uuid=True))
    actor_type = Column(String(50), nullable=False)
    action = Column(String(255), nullable=False)
    resource_type = Column(String(100))
    resource_id = Column(UUID(as_uuid=True))
    status = Column(String(50))
    ip_address = Column(String(45))
    metadata_info = Column(JSONB) # avoid using 'metadata'

class CostLedger(Base):
    """Granular tracker for LLM token usage (Input/Output/Cache) allocating monetary costs to specific workflow runs."""
    __tablename__ = 'cost_ledger'
    org_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey('workflow_runs.id'))
    agent_id = Column(UUID(as_uuid=True), ForeignKey('agents.id'))
    cost_type = Column(String(50), nullable=False)
    provider = Column(String(50))
    model = Column(String(100))
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)
    thinking_tokens = Column(Integer, default=0)
    estimated_cost_usd = Column(Float, nullable=False, default=0.0)
