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

from sqlalchemy.orm import Session, joinedload

from backend.app.allocation import engine, repository, statistics
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


def run_allocation(db: Session, current_user: User) -> AllocationRunResponse:
    """Run the auto-allocation engine and persist the resulting plan.

    Flow: validate → load data → allocate → persist → audit.

    Args:
        db: Active SQLAlchemy session.
        current_user: Authenticated user who triggered the run.

    Returns:
        Summary of allocated and skipped students per department.

    Raises:
        NoPendingStudentsError: When every student already has a mentor assigned.
    """
    from backend.app.allocation.validators import validate_has_pending_students
    validate_has_pending_students(db)

    unallocated_students = repository.get_unallocated_students(db)
    mentors_by_department = repository.get_mentors_by_department(db)
    workload_map = repository.get_workload_map(db)

    students_by_dept = _group_students_by_department(unallocated_students)
    mentors_for_engine = {
        dept: [{"id": m.id, "max_mentees": m.max_mentees} for m in mentors]
        for dept, mentors in mentors_by_department.items()
    }

    result = engine.allocate(students_by_dept, mentors_for_engine, workload_map)
    plan = result["plan"]

    if plan:
        repository.commit_allocation_plan(db, plan, current_user.id)

    run_stats = result["stats"]
    _record_allocation_audit(db, current_user.id, run_stats)

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


def _group_students_by_department(
    students: list[Student],
) -> dict[str, list[dict[str, Any]]]:
    """Group unallocated students by department for the allocation engine."""
    students_by_dept: dict[str, list[dict[str, Any]]] = {}
    for student in students:
        students_by_dept.setdefault(student.department, []).append(
            {"id": student.id, "success_score": student.success_score}
        )
    return students_by_dept


def _record_allocation_audit(
    db: Session,
    user_id: int,
    run_stats: dict[str, Any],
) -> None:
    """Write an audit entry for a completed allocation run."""
    write_audit(
        db=db,
        user_id=user_id,
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
    students = (
        db.query(Student)
        .options(joinedload(Student.user))
        .filter(Student.mentor_id.is_(None))
        .order_by(Student.success_score.desc().nullslast(), Student.id)
        .all()
    )
    return [
        PendingStudent(
            id=s.id,
            usn=s.usn,
            full_name=s.user.full_name if s.user else "",
            department=s.department,
            risk_status=s.risk_status,
            success_score=s.success_score,
        )
        for s in students
    ]