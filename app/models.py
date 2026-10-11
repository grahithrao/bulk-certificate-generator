import uuid
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(UTC)


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class RecipientStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_name = Column(String(200), nullable=False)
    issuer_name = Column(String(200), nullable=False)
    issue_date = Column(String(20), nullable=False)  # Stored as ISO YYYY-MM-DD
    status = Column(String(30), nullable=False, default=JobStatus.QUEUED.value, index=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    recipients = relationship(
        "Recipient",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="Recipient.input_index",
    )

    def __repr__(self) -> str:
        return f"<Job id={self.id} status={self.status} event={self.event_name[:20]}>"


class Recipient(Base):
    __tablename__ = "recipients"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    input_index = Column(Integer, nullable=False)

    # Input details (safe strings preserved)
    raw_name = Column(String(200), nullable=True)
    raw_email = Column(String(255), nullable=True)
    normalized_email = Column(String(255), nullable=True, index=True)

    # Processing status and error info
    status = Column(String(30), nullable=False, default=RecipientStatus.PENDING.value, index=True)
    error_code = Column(String(50), nullable=True)
    error_message = Column(String(500), nullable=True)

    # Certificate details
    certificate_id = Column(String(64), unique=True, index=True, nullable=True)
    relative_pdf_path = Column(String(255), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    job = relationship("Job", back_populates="recipients")

    __table_args__ = (
        Index("ix_recipients_job_status", "job_id", "status"),
        Index("ix_recipients_job_index", "job_id", "input_index"),
    )

    def __repr__(self) -> str:
        return f"<Recipient id={self.id} job_id={self.job_id} index={self.input_index} status={self.status}>"
