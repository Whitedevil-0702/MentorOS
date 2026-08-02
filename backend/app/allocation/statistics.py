"""Statistics aggregation helpers for the allocation module."""
from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from backend.app.allocation.repository import get_allocation_stats
from backend.app.allocation.schemas import (
    AllocationStatistics,
    DepartmentStatistics,
    MenteeSummary,
    MentorWorkload,
)
from backend.app.models.mentor import Mentor
from backend.app.models.student import Student


def build_statistics(db: Session) -> AllocationStatistics:
    """Build aggregate allocation statistics for the statistics endpoint.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        ``AllocationStatistics`` with totals and per-department breakdown.
    """
    raw = get_allocation_stats(db)
    by_department = {
        department: DepartmentStatistics(**counts)
        for department, counts in raw["by_department"].items()
    }
    return AllocationStatistics(
        total_students=raw["total_students"],
        total_mentors=raw["total_mentors"],
        allocated=raw["allocated"],
        pending=raw["pending"],
        by_department=by_department,
    )


def build_workload(db: Session) -> list[MentorWorkload]:
    """Build per-mentor workload breakdown with assigned mentee lists.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        One ``MentorWorkload`` entry per mentor, including current load and mentees.
    """
    mentors = (
        db.query(Mentor)
        .options(
            joinedload(Mentor.user),
            joinedload(Mentor.students).joinedload(Student.user),
        )
        .all()
    )

    return [_build_mentor_workload(mentor) for mentor in mentors]


def _build_mentor_workload(mentor: Mentor) -> MentorWorkload:
    """Build a ``MentorWorkload`` entry for a single mentor."""
    mentees = [
        MenteeSummary(
            id=student.id,
            usn=student.usn,
            full_name=student.user.full_name if student.user else "",
            risk_status=student.risk_status,
        )
        for student in mentor.students
    ]
    mentor_name = mentor.user.full_name if mentor.user else ""

    return MentorWorkload(
        mentor_id=mentor.id,
        mentor_name=mentor_name,
        department=mentor.department,
        current=len(mentees),
        max=mentor.max_mentees,
        mentees=mentees,
    )