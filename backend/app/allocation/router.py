"""FastAPI routes for the allocation module."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.allocation.exceptions import AllocationModuleError
from backend.app.allocation.schemas import (
    AllocationResetResponse,
    AllocationRunResponse,
    AllocationStatistics,
    MentorWorkload,
    PendingStudent,
)
from backend.app.allocation.service import (
    get_pending,
    get_statistics,
    get_workload,
    reset_allocation,
    run_allocation,
)
from backend.app.auth.router import require_role
from backend.app.core.database import get_db
from backend.app.models.user import User

router = APIRouter()


def _raise_allocation_error(exc: AllocationModuleError) -> HTTPException:
    """Raise an HTTPException mapped from an allocation exception."""
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/run", response_model=AllocationRunResponse)
def run_allocation_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("HOD", "Admin")),
) -> AllocationRunResponse:
    """Run the auto-allocation engine for all unallocated students."""
    try:
        return run_allocation(db, current_user)
    except AllocationModuleError as exc:
        raise _raise_allocation_error(exc)


@router.post("/reset", response_model=AllocationResetResponse)
def reset_allocation_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("Admin")),
) -> AllocationResetResponse:
    """Clear all allocation records and reset student mentor assignments."""
    try:
        return reset_allocation(db, current_user)
    except AllocationModuleError as exc:
        raise _raise_allocation_error(exc)


@router.get("/statistics", response_model=AllocationStatistics)
def get_statistics_endpoint(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("HOD", "Admin")),
) -> AllocationStatistics:
    """Return aggregate allocation statistics across all departments."""
    try:
        return get_statistics(db)
    except AllocationModuleError as exc:
        raise _raise_allocation_error(exc)


@router.get("/workload", response_model=list[MentorWorkload])
def get_workload_endpoint(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("HOD", "Admin", "Mentor")),
) -> list[MentorWorkload]:
    """Return per-mentor workload and assigned mentee breakdown."""
    try:
        return get_workload(db)
    except AllocationModuleError as exc:
        raise _raise_allocation_error(exc)


@router.get("/pending", response_model=list[PendingStudent])
def get_pending_endpoint(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("HOD", "Admin")),
) -> list[PendingStudent]:
    """Return students awaiting mentor assignment."""
    try:
        return get_pending(db)
    except AllocationModuleError as exc:
        raise _raise_allocation_error(exc)