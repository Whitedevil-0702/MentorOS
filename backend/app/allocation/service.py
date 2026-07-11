"""Business logic orchestration for the allocation module.

The allocation run is a simple workflow:
  1. Validate there are unallocated students.
  2. Load unallocated students (with their success_score), mentors by
     department, and current mentor workloads from the repository.
  3. Hand the data to the pure allocation engine, which ranks students by
     success_score and assigns each to the least-loaded mentor in the same
     department.
  4. Persist the plan and record an audit entry.

The engine only consumes the success_score already produced by the Scoring
Engine — it never calculates or interprets that score.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.allocation import engine, repository, statistics, validators
from backend.app.allocation.schemas import (
    AllocationResetResponse,
    AllocationRunResponse,
    AllocationStatistics,
    DepartmentRunStats,
    MentorWorkload,
    PendingStudent,
)
from backend.app.core.audit import write_audit
from backend.app.models.mentor import Mentor
from backend.app.models.student import Student
from backend.app.models.user import User


def _students_by_department(students: list[Student]) -> dict[str, list[dict[str, Any]]]:
    """Group unallocated students into engine-ready dicts keyed by department.

    Each dict carries the ``success_score`` the engine ranks on — already
    computed and stored by the Scoring Engine. Risk status is intentionally
    excluded: it is display-only and must not affect allocation.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for student in students:
        grouped.setdefault(student.department, []).append(
            {
                "id": student.id,
                "success_score": student.success_score,
            }
        )
    return grouped


def _mentors_for_engine(
    mentors_by_department: dict[str, list[Mentor]],
) -> dict[str, list[dict[str, Any]]]:
    """Convert mentor ORM objects into engine-ready dicts keyed by department."""
    return {
        department: [
            {"id": mentor.id, "max_mentees": mentor.max_mentees}
            for mentor in mentors
        ]
        for department, mentors in mentors_by_department.items()
    }


def _pending_from_student(student: Student) -> PendingStudent:
    """Map a ``Student`` ORM row to a ``PendingStudent`` response schema."""
    user = getattr(student, "user", None)
    return PendingStudent(
        id=student.id,
        usn=student.usn,
        full_name=user.full_name if user is not None else "",
        department=student.department,
        risk_status=student.risk_status,
        success_score=student.success_score,
    )


def run_allocation(db: Session, current_user: User) -> AllocationRunResponse:
    """Run the auto-allocation engine and persist the resulting plan.

    Flow: validators → repository (load) → engine → repository (commit) → audit.

    Args:
        db: Active SQLAlchemy session.
        current_user: Authenticated user who triggered the run.

    Returns:
        Summary of allocated and skipped students per department.
    """
    validators.validate_has_pending_students(db)

    unallocated_students = repository.get_unallocated_students(db)
    mentors_by_department = repository.get_mentors_by_department(db)
    workload_map = repository.get_workload_map(db)

    result = engine.allocate(
        _students_by_department(unallocated_students),
        _mentors_for_engine(mentors_by_department),
        workload_map,
    )
    plan = result["plan"]

    if plan:
        repository.commit_allocation_plan(db, plan, current_user.id)

    run_stats = result["stats"]
    write_audit(
        db=db,
        user_id=current_user.id,
        action="run_allocation",
        entity_type="allocation",
        entity_id=None,
        details={
            "allocated": run_stats["allocated"],
            "skipped": run_stats["skipped"],
            "skipped_students": run_stats.get("skipped_students", []),
            "method": "auto",
        },
    )

    by_department = {
        department: DepartmentRunStats(**dept_stats)
        for department, dept_stats in run_stats["by_dept"].items()
    }
    return AllocationRunResponse(
        allocated=run_stats["allocated"],
        skipped=run_stats["skipped"],
        skipped_students=run_stats.get("skipped_students", []),
        by_department=by_department,
    )


def reset_allocation(db: Session, current_user: User) -> AllocationResetResponse:
    """Clear all allocations and reset live mentor assignments.

    Args:
        db: Active SQLAlchemy session.
        current_user: Authenticated admin who triggered the reset.

    Returns:
        Number of allocation records cleared.
    """
    cleared = repository.reset_all_allocations(db)
    write_audit(
        db=db,
        user_id=current_user.id,
        action="reset_allocation",
        entity_type="allocation",
        entity_id=None,
        details={"cleared": cleared},
    )
    return AllocationResetResponse(cleared=cleared)


def get_statistics(db: Session) -> AllocationStatistics:
    """Return aggregate allocation statistics.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        ``AllocationStatistics`` for the statistics endpoint.
    """
    return statistics.build_statistics(db)


def get_workload(db: Session) -> list[MentorWorkload]:
    """Return per-mentor workload breakdown.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        Workload entry for each mentor.
    """
    return statistics.build_workload(db)


def get_pending(db: Session) -> list[PendingStudent]:
    """Return students awaiting mentor assignment, highest success_score first.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        Unallocated students ordered by success_score.
    """
    students = repository.get_unallocated_students(db)
    return [_pending_from_student(student) for student in students]
