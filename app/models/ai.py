from sqlalchemy import Column, String, Boolean, ForeignKey, Integer, Float, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from .base import Base

class Agent(Base):
    """Defines an autonomous AI agent configuration, including its designated model and system prompt."""
    __tablename__ = 'agents'
    org_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False)
    description = Column(String)
    agent_type = Column(String(50), nullable=False, default='specialist')
    
    model = Column(String(100), default='claude-3-7-sonnet-20250219')
    system_prompt = Column(String, nullable=False)
    context_window_tokens = Column(Integer, default=200000)
    max_output_tokens = Column(Integer, default=4096)
    temperature = Column(Float, default=0.3)
    
    a2a_endpoint = Column(String)
    team_role = Column(String(50))
    a2a_manifest = Column(JSONB)
    
    extended_thinking = Column(Boolean, default=False)
    extended_thinking_config = Column(JSONB, default=dict)
    policy_scope = Column(JSONB, default=dict)
    allowed_mcp_servers = Column(JSONB, default=list)
    
    is_active = Column(Boolean, default=True)
    version = Column(Integer, default=1)
    created_by = Column(UUID(as_uuid=True), ForeignKey('users.id'))

class AgentTeam(Base):
    """Groups multiple Agents into a cohesive unit for parallel A2A (Agent-to-Agent) execution."""
    __tablename__ = 'agent_teams'
    org_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(String)
    orchestrator_agent_id = Column(UUID(as_uuid=True), ForeignKey('agents.id'))
    a2a_manifest = Column(JSONB)
    max_agent_hops = Column(Integer, default=10)
    parallel_execution = Column(Boolean, default=True)
    timeout_seconds = Column(Integer, default=600)
    is_active = Column(Boolean, default=True)

class AgentTeamMember(Base):
    """Association table mapping individual Agents to specific AgentTeams with designated roles."""
    __tablename__ = 'agent_team_members'
    id = Column(UUID(as_uuid=True), primary_key=True) # Adding UUID internally though the exact design might use tuple composite keys, SQLAlchemy prefers single PK for simplicity
    team_id = Column(UUID(as_uuid=True), ForeignKey('agent_teams.id', ondelete='CASCADE'))
    agent_id = Column(UUID(as_uuid=True), ForeignKey('agents.id', ondelete='CASCADE'))
    role = Column(String(50), nullable=False)
    priority = Column(Integer, default=0)

class Workflow(Base):
    """Defines a LangGraph orchestration pipeline template with triggers and automated schedules."""
    __tablename__ = 'workflows'
    org_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey('agents.id'), nullable=False)
    team_id = Column(UUID(as_uuid=True), ForeignKey('agent_teams.id'))
    name = Column(String(255), nullable=False)
    description = Column(String)
    trigger_type = Column(String(50), nullable=False)
    graph_definition = Column(JSONB, nullable=False)
    input_schema = Column(JSONB)
    output_schema = Column(JSONB)
    max_agent_hops = Column(Integer, default=10)
    a2a_enabled = Column(Boolean, default=False)
    requires_approval = Column(Boolean, default=False)
    approval_conditions = Column(JSONB, default=list)
    cron_expression = Column(String(100))
    timezone = Column(String(50), default='UTC')
    next_run_at = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)
    version = Column(Integer, default=1)
    created_by = Column(UUID(as_uuid=True), ForeignKey('users.id'))

class WorkflowRun(Base):
    """A materialized execution trace representing a single run of a Workflow."""
    __tablename__ = 'workflow_runs'
    workflow_id = Column(UUID(as_uuid=True), ForeignKey('workflows.id'), nullable=False)
    org_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False)
    triggered_by = Column(UUID(as_uuid=True), ForeignKey('users.id'))
    status = Column(String(50), nullable=False, default='pending')
    run_trace = Column(JSONB)

class WorkflowStep(Base):
    """A granular audit trace of a specific action, LLM reasoning step, or MCP tool call within a run."""
    __tablename__ = 'workflow_steps'
    run_id = Column(UUID(as_uuid=True), ForeignKey('workflow_runs.id', ondelete='CASCADE'), nullable=False)
    node_name = Column(String(255), nullable=False)
    step_type = Column(String(50), nullable=False)
    input_data = Column(JSONB)
    output_data = Column(JSONB)
    duration_ms = Column(Integer)
    status = Column(String(50), default='completed')

class Approval(Base):
    """A human-in-the-loop (HITL) gate that pauses an agent until a human authorizes the proposed action."""
    __tablename__ = 'approvals'
    run_id = Column(UUID(as_uuid=True), ForeignKey('workflow_runs.id'), nullable=False)
    org_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False)
    status = Column(String(50), default='pending')
    context_data = Column(JSONB)
    
class ApprovalDecision(Base):
    """The cryptographically recorded accept/reject decision made by a human acting on an Approval gate."""
    __tablename__ = 'approval_decisions'
    approval_id = Column(UUID(as_uuid=True), ForeignKey('approvals.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'))
    decision = Column(String(50), nullable=False)
    reason = Column(String)
