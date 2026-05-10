from sqlalchemy import Column, String, Boolean, ForeignKey, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from .base import Base

class Document(Base):
    """A primary source document (PDF, TXT) uploaded to S3 for processing into the knowledge base."""
    __tablename__ = 'documents'
    org_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    filename = Column(String(255), nullable=False)
    s3_path = Column(String, nullable=False)
    mime_type = Column(String(100))
    byte_size = Column(Integer)
    processing_status = Column(String(50), default='pending')
    vector_id = Column(String)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey('users.id'))

class DocumentChunk(Base):
    """A chunked subset of a Document, tracking its mapping to embedding vectors stored in Pinecone."""
    __tablename__ = 'document_chunks'
    doc_id = Column(UUID(as_uuid=True), ForeignKey('documents.id', ondelete='CASCADE'), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    pinecone_id = Column(String(255), nullable=False)

class VectorNamespace(Base):
    """Tracks logical isolation namespaces within Pinecone to permanently separate organization data."""
    __tablename__ = 'vector_namespaces'
    org_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    namespace = Column(String(255), unique=True, nullable=False)
    description = Column(String)
