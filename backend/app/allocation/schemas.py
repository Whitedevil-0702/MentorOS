"""Pydantic v2 request/response schemas for the allocation module."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DepartmentRunStats(BaseModel):
    """Allocation run results for a single department."""

    allocated: int
    skipped: int


class AllocationRunResponse(BaseModel):
    """Response returned after running the auto-allocation engine."""

    allocated: int
    skipped: int
    skipped_students: list[int] = []
    by_department: dict[str, DepartmentRunStats]


class AllocationResetResponse(BaseModel):
    """Response returned after clearing all allocations."""

    cleared: int


class DepartmentStatistics(BaseModel):
    """Per-department summary for the statistics endpoint."""

    total_students: int
    total_mentors: int
    allocated: int
    pending: int


class AllocationStatistics(BaseModel):
    """Aggregate allocation statistics across all departments."""

    total_students: int
    total_mentors: int
    allocated: int
    pending: int
    by_department: dict[str, DepartmentStatistics]


class MenteeSummary(BaseModel):
    """A student assigned to a mentor, shown in workload breakdown."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    usn: str
    full_name: str
    risk_status: str


class MentorWorkload(BaseModel):
    """Current mentor load versus capacity."""

    model_config = ConfigDict(from_attributes=True)

    mentor_id: int
    mentor_name: str
    department: str
    current: int
    max: int
    mentees: list[MenteeSummary]


class PendingStudent(BaseModel):
    """Student awaiting mentor assignment."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    usn: str
    full_name: str
    department: str
    risk_status: str
    success_score: float | None = None
