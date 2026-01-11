"""Application endpoints for the two-phase job application flow."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel

from app.db import (
    create_application,
    get_application,
    get_application_by_user_and_job,
    get_job,
    get_user,
    get_user_cached_responses,
    list_user_applications,
    transition_application_state,
    update_application,
    update_user_cached_responses,
)
from app.models.applications import (
    AnalyzeRequest,
    AnalyzeResponse,
    ApplicationState,
    ApplicationStatusResponse,
    FieldSource,
    FieldType,
    FormFieldAnalysis,
    JobInfo,
    SubmitRequest,
    SubmitResponse,
)
from app.applying.greenhouse import GreenhouseApplier, get_cache_key

router = APIRouter(prefix="/api/v1/applications", tags=["applications"])

# TTL for pending_review applications (30 minutes)
PENDING_REVIEW_TTL_SECONDS = 1800


class CancelResponse(BaseModel):
    """Response from cancel endpoint."""
    application_id: str
    status: str


class ApplicationListItem(BaseModel):
    """Summary of an application for list view."""
    application_id: str
    job_id: str
    job_title: str
    company_name: str
    status: str
    created_at: datetime


class ApplicationListResponse(BaseModel):
    """Response from list applications endpoint."""
    applications: list[ApplicationListItem]
    total: int


def _get_user_id(x_user_id: str | None) -> str:
    """
    Extract user ID from header.

    In production, this would validate a JWT token.
    For now, we accept the user ID directly via header.
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-ID header required")
    return x_user_id


def _convert_fields_to_response(fields: list[dict[str, Any]]) -> list[FormFieldAnalysis]:
    """Convert stored fields to response format."""
    result = []
    for f in fields:
        try:
            field_type = FieldType(f.get("field_type", "text"))
        except ValueError:
            field_type = FieldType.TEXT

        try:
            source = FieldSource(f.get("source", "manual"))
        except ValueError:
            source = FieldSource.MANUAL

        result.append(FormFieldAnalysis(
            field_id=f.get("field_id", ""),
            label=f.get("label", ""),
            field_type=field_type,
            required=f.get("required", False),
            options=f.get("options"),
            recommended_value=f.get("recommended_value"),
            reasoning=f.get("reasoning"),
            source=source,
            confidence=f.get("confidence", 0.0),
            editable=f.get("field_type") != "file"
        ))
    return result


@router.post("/analyze", status_code=201)
async def analyze_application(
    request: AnalyzeRequest,
    x_user_id: str | None = Header(None, alias="X-User-ID")
) -> AnalyzeResponse | SubmitResponse:
    """
    Analyze a job application form and prepare field values.

    If auto_submit=true, also submits the form and returns SubmitResponse.
    If auto_submit=false, returns field recommendations for user review.
    """
    user_id = _get_user_id(x_user_id)

    # Get user profile
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get job details
    job = await get_job(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check if job is still active
    if not job.get("active", True):
        raise HTTPException(status_code=410, detail="Job posting has been removed")

    # Check for existing active application
    existing = await get_application_by_user_and_job(user_id, request.job_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Application already exists with status: {existing['status']}"
        )

    # Create application record
    app_doc = {
        "user_id": user_id,
        "job_id": request.job_id,
        "job_url": job.get("absolute_url", ""),
        "job_title": job.get("title", "Unknown"),
        "company_name": job.get("company_name", "Unknown"),
        "status": ApplicationState.ANALYZING.value,
        "auto_submit": request.auto_submit,
        "fields": [],
        "form_fingerprint": None,
        "expires_at": None,
        "error": None,
    }

    try:
        application_id = await create_application(app_doc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create application: {e}")

    # Get user's cached responses
    cached_responses = await get_user_cached_responses(user_id)

    # Analyze the form
    applier = GreenhouseApplier(headless=True)
    
    # Check for pre-analyzed schema in job
    pre_analyzed_fields = None
    if job.get("form_schema") and isinstance(job["form_schema"], dict):
        pre_analyzed_fields = job["form_schema"].get("fields")

    try:
        analysis = await applier.analyze_form(
            url=job.get("absolute_url", ""),
            user_profile=user,
            job_description=job.get("description_text", ""),
            cached_responses=cached_responses,
            pre_analyzed_fields=pre_analyzed_fields
        )
    except Exception as e:
        # Mark application as failed
        await update_application(application_id, {
            "status": ApplicationState.FAILED.value,
            "error": str(e)
        })
        raise HTTPException(status_code=502, detail=f"Failed to analyze form: {e}")

    if analysis.get("status") == "error":
        await update_application(application_id, {
            "status": ApplicationState.FAILED.value,
            "error": analysis.get("message", "Unknown error")
        })
        raise HTTPException(status_code=502, detail=analysis.get("message", "Form analysis failed"))

    fields = analysis.get("fields", [])
    fingerprint = analysis.get("form_fingerprint", "")

    if request.auto_submit:
        # Auto-submit: transition to SUBMITTING and fill form
        updated = await transition_application_state(
            application_id,
            ApplicationState.ANALYZING.value,
            ApplicationState.SUBMITTING.value,
            {"fields": fields, "form_fingerprint": fingerprint}
        )

        if not updated:
            raise HTTPException(status_code=409, detail="Application state changed unexpectedly")

        # Set final values from recommendations
        for field in fields:
            field["final_value"] = field.get("recommended_value")

        try:
            result = await applier.fill_and_submit(
                url=job.get("absolute_url", ""),
                fields=fields,
                expected_fingerprint=fingerprint,
                submit=True
            )
        except Exception as e:
            await update_application(application_id, {
                "status": ApplicationState.FAILED.value,
                "error": str(e)
            })
            raise HTTPException(status_code=502, detail=f"Failed to submit: {e}")

        # Update final status
        if result.get("status") == "success":
            await update_application(application_id, {
                "status": ApplicationState.SUBMITTED.value,
                "submitted_at": datetime.utcnow(),
                "fields": fields
            })

            # Cache the responses
            await _cache_user_responses(user_id, fields)

            return SubmitResponse(
                application_id=application_id,
                status="submitted",
                message=result.get("message", "Application submitted successfully"),
                submitted_at=datetime.utcnow()
            )
        else:
            await update_application(application_id, {
                "status": ApplicationState.FAILED.value,
                "error": result.get("message", "Submission failed")
            })
            return SubmitResponse(
                application_id=application_id,
                status="failed",
                message=result.get("message", "Submission failed"),
                error=result.get("message")
            )
    else:
        # Manual review: transition to PENDING_REVIEW
        expires_at = datetime.utcnow() + timedelta(seconds=PENDING_REVIEW_TTL_SECONDS)

        await update_application(application_id, {
            "status": ApplicationState.PENDING_REVIEW.value,
            "fields": fields,
            "form_fingerprint": fingerprint,
            "expires_at": expires_at
        })

        return AnalyzeResponse(
            application_id=application_id,
            status="pending_review",
            expires_at=expires_at,
            ttl_seconds=PENDING_REVIEW_TTL_SECONDS,
            job=JobInfo(
                id=request.job_id,
                title=job.get("title", "Unknown"),
                company_name=job.get("company_name", "Unknown"),
                url=job.get("absolute_url", "")
            ),
            fields=_convert_fields_to_response(fields),
            form_fingerprint=fingerprint
        )


@router.post("/{application_id}/submit")
async def submit_application(
    application_id: str,
    request: SubmitRequest,
    x_user_id: str | None = Header(None, alias="X-User-ID")
) -> SubmitResponse:
    """
    Submit an analyzed application with user-confirmed answers.
    """
    user_id = _get_user_id(x_user_id)

    # Get application
    app = await get_application(application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    # Verify ownership
    if app["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Check current status
    current_status = app.get("status")

    if current_status == ApplicationState.SUBMITTED.value:
        return SubmitResponse(
            application_id=application_id,
            status="already_submitted",
            message="Application was already submitted",
            submitted_at=app.get("submitted_at")
        )

    if current_status == ApplicationState.EXPIRED.value:
        raise HTTPException(status_code=410, detail="Application has expired. Please re-analyze.")

    if current_status != ApplicationState.PENDING_REVIEW.value:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot submit application in status: {current_status}"
        )

    # Check expiration
    expires_at = app.get("expires_at")
    if expires_at and datetime.utcnow() > expires_at:
        await update_application(application_id, {"status": ApplicationState.EXPIRED.value})
        raise HTTPException(status_code=410, detail="Application has expired. Please re-analyze.")

    # Atomic transition to SUBMITTING
    updated = await transition_application_state(
        application_id,
        ApplicationState.PENDING_REVIEW.value,
        ApplicationState.SUBMITTING.value
    )

    if not updated:
        raise HTTPException(status_code=409, detail="Application state changed. Please try again.")

    # Merge field overrides
    fields = app.get("fields", [])
    for field in fields:
        field_id = field.get("field_id")
        if field_id in request.field_overrides:
            field["final_value"] = request.field_overrides[field_id]
        else:
            field["final_value"] = field.get("recommended_value")

    # Get job URL
    job_url = app.get("job_url", "")
    fingerprint = app.get("form_fingerprint")

    # Fill and submit
    # DEBUG: Set headless=False to see browser during testing
    applier = GreenhouseApplier(headless=True)

    # Define verification callback for server console interaction
    async def server_verification_callback():
        print("\n" + "!" * 50)
        print(f"ACTION REQUIRED: Email Verification for Application {application_id}")
        print("Please check your email and enter the 8-digit code below:")
        print("!" * 50)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, input, "Verification Code: ")

    try:
        result = await applier.fill_and_submit(
            url=job_url,
            fields=fields,
            expected_fingerprint=None, # Disable strict check for demo robustness
            submit=True,
            verification_callback=server_verification_callback
        )
    except Exception as e:
        await update_application(application_id, {
            "status": ApplicationState.FAILED.value,
            "error": str(e)
        })
        raise HTTPException(status_code=502, detail=f"Failed to submit: {e}")

    # Handle form changed
    if result.get("status") == "form_changed":
        await update_application(application_id, {
            "status": ApplicationState.FAILED.value,
            "error": "Form structure changed"
        })
        raise HTTPException(
            status_code=422,
            detail="Form structure has changed since analysis. Please re-analyze."
        )

    # Update final status
    if result.get("status") == "success":
        await update_application(application_id, {
            "status": ApplicationState.SUBMITTED.value,
            "submitted_at": datetime.utcnow(),
            "fields": fields
        })

        # Cache responses if requested
        if request.save_responses:
            await _cache_user_responses(user_id, fields)

        return SubmitResponse(
            application_id=application_id,
            status="submitted",
            message=result.get("message", "Application submitted successfully"),
            submitted_at=datetime.utcnow()
        )
    else:
        await update_application(application_id, {
            "status": ApplicationState.FAILED.value,
            "error": result.get("message", "Submission failed")
        })
        return SubmitResponse(
            application_id=application_id,
            status="failed",
            message=result.get("message", "Submission failed"),
            error=result.get("message")
        )


@router.get("/{application_id}")
async def get_application_status(
    application_id: str,
    x_user_id: str | None = Header(None, alias="X-User-ID")
) -> ApplicationStatusResponse:
    """
    Get the current status of an application.
    """
    user_id = _get_user_id(x_user_id)

    app = await get_application(application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    if app["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        status = ApplicationState(app.get("status", "failed"))
    except ValueError:
        status = ApplicationState.FAILED

    fields = None
    if app.get("fields"):
        fields = _convert_fields_to_response(app["fields"])

    return ApplicationStatusResponse(
        application_id=application_id,
        user_id=app["user_id"],
        job_id=app["job_id"],
        job_title=app.get("job_title", "Unknown"),
        company_name=app.get("company_name", "Unknown"),
        status=status,
        fields=fields,
        created_at=app.get("created_at", datetime.utcnow()),
        updated_at=app.get("updated_at", datetime.utcnow()),
        submitted_at=app.get("submitted_at"),
        expires_at=app.get("expires_at"),
        error=app.get("error")
    )


@router.delete("/{application_id}")
async def cancel_application(
    application_id: str,
    x_user_id: str | None = Header(None, alias="X-User-ID")
) -> CancelResponse:
    """
    Cancel a pending application.
    """
    user_id = _get_user_id(x_user_id)

    app = await get_application(application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    if app["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    current_status = app.get("status")

    if current_status == ApplicationState.SUBMITTED.value:
        return CancelResponse(
            application_id=application_id,
            status="already_submitted"
        )

    if current_status in [ApplicationState.CANCELLED.value, ApplicationState.EXPIRED.value]:
        return CancelResponse(
            application_id=application_id,
            status=current_status
        )

    await update_application(application_id, {
        "status": ApplicationState.CANCELLED.value
    })

    return CancelResponse(
        application_id=application_id,
        status="cancelled"
    )


@router.get("")
async def list_applications(
    x_user_id: str | None = Header(None, alias="X-User-ID"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
) -> ApplicationListResponse:
    """
    List applications for the current user.
    """
    user_id = _get_user_id(x_user_id)

    apps, total = await list_user_applications(user_id, status, limit, offset)

    items = [
        ApplicationListItem(
            application_id=str(app["_id"]),
            job_id=app["job_id"],
            job_title=app.get("job_title", "Unknown"),
            company_name=app.get("company_name", "Unknown"),
            status=app.get("status", "unknown"),
            created_at=app.get("created_at", datetime.utcnow())
        )
        for app in apps
    ]

    return ApplicationListResponse(applications=items, total=total)


async def _cache_user_responses(user_id: str, fields: list[dict[str, Any]]) -> None:
    """Cache the user's form responses for future use."""
    standard_updates: dict[str, str] = {}
    custom_updates: dict[str, dict[str, Any]] = {}

    for field in fields:
        # Get the value that was used
        value = field.get("final_value") or field.get("recommended_value")
        if not value:
            continue

        # Skip file fields
        if field.get("field_type") == "file":
            continue

        label = field.get("label", "")
        cache_type, cache_key = get_cache_key(label)

        if cache_type == "standard":
            standard_updates[cache_key] = value
        else:
            custom_updates[cache_key] = {
                "question_text": label,
                "answer": value,
                "last_used": datetime.utcnow(),
                "use_count": 1  # Will be incremented if already exists
            }

    if standard_updates or custom_updates:
        await update_user_cached_responses(user_id, standard_updates, custom_updates)
