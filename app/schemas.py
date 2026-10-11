from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.config import settings


class RecipientInput(BaseModel):
    """Schema for individual recipient input if structured."""
    name: Any | None = None
    email: Any | None = None


class JobCreateRequest(BaseModel):
    """
    Job creation payload.
    The envelope fields (event_name, issuer_name, issue_date, recipients list)
    are strictly validated. Individual recipient items are accepted as raw objects
    so that malformed individual entries do not fail the entire batch.
    """
    event_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Name of the course, workshop, or event",
        json_schema_extra={"example": "Python Backend Development Workshop"},
    )
    issuer_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Name of the issuing organization or academy",
        json_schema_extra={"example": "Example Learning Academy"},
    )
    issue_date: str = Field(
        ...,
        description="Issue date in YYYY-MM-DD format",
        json_schema_extra={"example": "2026-10-11"},
    )
    recipients: list[Any] = Field(
        ...,
        description="Array of recipient objects containing name and email",
        json_schema_extra={
            "example": [
                {"name": "Aarav Sharma", "email": "aarav@example.com"},
                {"name": "Diya Rao", "email": "diya@example.com"},
            ]
        },
    )

    @field_validator("event_name", "issuer_name")
    @classmethod
    def validate_non_blank(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Field must not be empty or contain only whitespace")
        return trimmed

    @field_validator("issue_date")
    @classmethod
    def validate_issue_date(cls, v: str) -> str:
        trimmed = v.strip()
        try:
            parsed = datetime.strptime(trimmed, "%Y-%m-%d").date()
            return parsed.isoformat()
        except ValueError:
            raise ValueError("Issue date must be a valid date in YYYY-MM-DD format")

    @field_validator("recipients")
    @classmethod
    def validate_recipients_envelope(cls, v: list[Any]) -> list[Any]:
        if not isinstance(v, list):
            raise ValueError("Recipients must be a JSON array")
        if len(v) == 0:
            raise ValueError("Recipients array must contain at least one recipient")
        if len(v) > settings.max_batch_size:
            raise ValueError(
                f"Batch size of {len(v)} exceeds maximum allowed limit of {settings.max_batch_size}"
            )
        return v


class JobCreateResponse(BaseModel):
    """Response returned upon submitting a bulk certificate job."""
    job_id: str
    status: str
    total: int
    accepted: int
    rejected: int
    status_url: str
    message: str


class JobCounters(BaseModel):
    total: int
    processed: int
    completed: int
    failed: int
    pending: int
    processing: int


class JobStatusResponse(BaseModel):
    """Detailed job status and progress information."""
    job_id: str
    event_name: str
    issuer_name: str
    issue_date: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    counts: JobCounters
    progress_percent: float
    recipients_url: str


class RecipientItemResponse(BaseModel):
    """Individual recipient processing outcome."""
    id: str
    input_index: int
    name: str | None = None
    email: str | None = None
    status: str
    error_code: str | None = None
    error_message: str | None = None
    certificate_id: str | None = None
    download_url: str | None = None
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None = None


class PaginatedRecipientsResponse(BaseModel):
    """Paginated list of recipient outcomes for a job."""
    job_id: str
    total: int
    page: int
    page_size: int
    total_pages: int
    items: list[RecipientItemResponse]


class HealthResponse(BaseModel):
    """System health check response."""
    status: str
    service: str
    owner: str
    timestamp: datetime
    version: str
