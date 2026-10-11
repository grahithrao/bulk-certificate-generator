from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import RecipientStatus
from app.schemas import (
    JobCounters,
    JobCreateRequest,
    JobCreateResponse,
    JobStatusResponse,
    PaginatedRecipientsResponse,
    RecipientItemResponse,
)
from app.services.jobs import (
    get_job_by_id,
    get_job_counters,
    get_paginated_recipients,
    get_recipient_by_certificate_id,
    validate_and_create_job,
)

router = APIRouter()


@router.post(
    "/jobs",
    response_model=JobCreateResponse,
    summary="Create a bulk certificate generation job",
    description=(
        "Accepts certificate information and a list of recipients. "
        "Validates the request envelope and each individual recipient. "
        "Returns HTTP 202 Accepted for batches with valid recipients to process asynchronously. "
        "Returns HTTP 201 Created if all recipients are invalid, providing a diagnostic job resource."
    ),
    responses={
        202: {"description": "Job accepted for background processing"},
        201: {"description": "Diagnostic job created for an all-invalid batch"},
        422: {"description": "Malformed job-level envelope or oversized batch"},
    },
)
def create_job(
    payload: JobCreateRequest,
    db: Session = Depends(get_db),
):
    job, accepted_count, rejected_count, is_all_invalid = validate_and_create_job(db, payload)

    total_submitted = len(payload.recipients)
    status_url = f"/api/v1/jobs/{job.id}"

    if is_all_invalid:
        response_data = JobCreateResponse(
            job_id=job.id,
            status=job.status,
            total=total_submitted,
            accepted=0,
            rejected=rejected_count,
            status_url=status_url,
            message="All recipients failed validation. A completed diagnostic job resource was created.",
        )
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=response_data.model_dump(),
        )

    response_data = JobCreateResponse(
        job_id=job.id,
        status=job.status,
        total=total_submitted,
        accepted=accepted_count,
        rejected=rejected_count,
        status_url=status_url,
        message="Job accepted for asynchronous certificate generation.",
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=response_data.model_dump(),
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status and generation progress",
    description="Returns high-level status, counters, timestamps, and a link to paginated recipient outcomes.",
    responses={
        200: {"description": "Job status and progress summary"},
        404: {"description": "Job not found"},
    },
)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' was not found.",
        )

    counters = get_job_counters(db, job_id)

    return JobStatusResponse(
        job_id=job.id,
        event_name=job.event_name,
        issuer_name=job.issuer_name,
        issue_date=job.issue_date,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        counts=JobCounters(
            total=counters["total"],
            processed=counters["processed"],
            completed=counters["completed"],
            failed=counters["failed"],
            pending=counters["pending"],
            processing=counters["processing"],
        ),
        progress_percent=counters["progress_percent"],
        recipients_url=f"/api/v1/jobs/{job.id}/recipients",
    )


@router.get(
    "/jobs/{job_id}/recipients",
    response_model=PaginatedRecipientsResponse,
    summary="Get paginated recipient outcomes for a job",
    description="Returns individual recipient outcomes, safe error details, certificate IDs, and download links.",
    responses={
        200: {"description": "Paginated recipient details"},
        404: {"description": "Job not found"},
    },
)
def get_job_recipients(
    job_id: str,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page (max 100)"),
    status_filter: str | None = Query(
        None,
        alias="status",
        description="Filter by recipient status (pending, processing, completed, failed)",
    ),
    db: Session = Depends(get_db),
):
    job = get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' was not found.",
        )

    if status_filter and status_filter not in [s.value for s in RecipientStatus]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid status filter. Allowed values: pending, processing, completed, failed.",
        )

    items, total_count, total_pages = get_paginated_recipients(
        db=db,
        job_id=job_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
    )

    response_items = []
    for item in items:
        dl_url = None
        if item.status == RecipientStatus.COMPLETED.value and item.certificate_id:
            dl_url = f"/api/v1/certificates/{item.certificate_id}/download"

        response_items.append(
            RecipientItemResponse(
                id=item.id,
                input_index=item.input_index,
                name=item.raw_name,
                email=item.raw_email,
                status=item.status,
                error_code=item.error_code,
                error_message=item.error_message,
                certificate_id=item.certificate_id,
                download_url=dl_url,
                created_at=item.created_at,
                updated_at=item.updated_at,
                processed_at=item.processed_at,
            )
        )

    return PaginatedRecipientsResponse(
        job_id=job.id,
        total=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        items=response_items,
    )


@router.get(
    "/certificates/{certificate_id}/download",
    summary="Download a generated certificate PDF",
    description="Streams the generated PDF for an existing, completed certificate. Resolves securely from database records.",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "Certificate PDF file"},
        404: {"description": "Certificate ID not found or file missing"},
        409: {"description": "Certificate is not yet ready or generation failed"},
    },
)
def download_certificate(
    certificate_id: str,
    db: Session = Depends(get_db),
):
    recipient = get_recipient_by_certificate_id(db, certificate_id)
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certificate ID '{certificate_id}' was not found.",
        )

    if recipient.status in (RecipientStatus.PENDING.value, RecipientStatus.PROCESSING.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Certificate is currently being generated and is not ready for download. Please poll the job status.",
        )

    if recipient.status == RecipientStatus.FAILED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Certificate generation failed for this recipient: {recipient.error_message or 'Unknown error'}",
        )

    if not recipient.relative_pdf_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generated certificate file record is missing.",
        )

    # Secure path resolution to prevent path traversal
    base_storage = settings.storage_dir.resolve()
    full_path = (settings.storage_dir / recipient.relative_pdf_path).resolve()

    # Verify that the path is strictly within the allowed storage directory
    try:
        full_path.relative_to(base_storage)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid certificate storage path.",
        )

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generated certificate PDF file is missing from local storage.",
        )

    # Safe sanitized filename for attachment header
    safe_filename = f"certificate_{certificate_id}.pdf"

    return FileResponse(
        path=str(full_path),
        media_type="application/pdf",
        filename=safe_filename,
    )


@router.get(
    "/certificates/preview",
    summary="Preview certificate template as PDF",
    description="Renders and streams a sample certificate PDF directly from the active template.",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "Rendered PDF preview"},
        422: {"description": "Validation error on preview parameters"},
    },
)
def preview_certificate(
    recipient_name: str = Query("Jane Doe", description="Recipient full name for sample preview"),
    event_name: str = Query(
        "Advanced Python Backend Development Workshop",
        description="Event name for sample preview",
    ),
    issuer_name: str = Query("Example Learning Academy", description="Issuer name for sample preview"),
    issue_date: str = Query("2026-10-11", description="Issue date (YYYY-MM-DD) for sample preview"),
    certificate_id: str = Query("SAMPLE-PREVIEW-001", description="Sample certificate ID"),
):
    from fastapi import Response
    from app.services.certificates import render_certificate_pdf_bytes

    try:
        pdf_bytes = render_certificate_pdf_bytes(
            recipient_name=recipient_name.strip() or "Jane Doe",
            event_name=event_name.strip() or "Event Name",
            issuer_name=issuer_name.strip() or "Issuing Organization",
            issue_date=issue_date.strip() or "2026-10-11",
            certificate_id=certificate_id.strip() or "SAMPLE-0001",
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="certificate_preview.pdf"'},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unable to generate certificate preview: {str(e)}",
        )
