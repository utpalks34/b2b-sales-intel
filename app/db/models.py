"""
app/db/models.py

SQLAlchemy ORM models mirroring app/db/schema.sql exactly (already
executed against orchestrator_db in Phase 1 -- these models describe
that existing schema, they don't create it. If schema.sql ever changes,
update it there first, then here).
"""
from __future__ import annotations

import uuid

from sqlalchemy import Column, Float, ForeignKey, Integer, String, TIMESTAMP, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Company(Base):
    __tablename__ = "companies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain = Column(String, unique=True, nullable=False)
    company_name = Column(String)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    sources = relationship("Source", back_populates="company", cascade="all, delete-orphan")
    decision_makers = relationship("DecisionMaker", back_populates="company", cascade="all, delete-orphan")
    signals = relationship("Signal", back_populates="company", cascade="all, delete-orphan")
    email_drafts = relationship("EmailDraft", back_populates="company", cascade="all, delete-orphan")


class Source(Base):
    __tablename__ = "sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"))
    url = Column(Text, nullable=False)
    source_type = Column(String)
    scraped_via = Column(String)
    content = Column(Text)
    fetched_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="sources")


class DecisionMaker(Base):
    __tablename__ = "decision_makers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"))
    name = Column(String)
    title = Column(String)
    source_confidence = Column(Float)

    company = relationship("Company", back_populates="decision_makers")


class Signal(Base):
    __tablename__ = "signals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"))
    signal_type = Column(String)
    description = Column(Text)

    company = relationship("Company", back_populates="signals")


class EmailDraft(Base):
    __tablename__ = "email_drafts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"))
    run_id = Column(UUID(as_uuid=True), nullable=False)
    version = Column(Integer, nullable=False)
    body = Column(Text)
    critic_score = Column(Float)
    critic_feedback = Column(Text)
    status = Column(String)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="email_drafts")