"""Database access layer for the allocation module."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from backend.app.allocation.models import Allocation
from backend.app.models.mentor import Mentor
from backend.app.models.student import Student

def _student_score_sort_key(student: Student) -> tuple[float, int]:
    """Sort key: highest ``success_score`` first, ``id`` breaks ties.

    Unscored students (``success_score`` None) sink to the bottom so they are
    allocated last rather than jumping the queue.

    This is the SAME rule the engine uses (engine._sort_key) so the "pending"
    view and the allocation run agree on who is allocated first.
    """
    return (-(student.success_score or 0), student.id)


def get_unallocated_students(db: Session) -> list[Student]:
    """Return students with no mentor assigned, ordered by score priority.

    Ordering is highest ``success_score`` → lowest, then by ``id``. This mirrors
    the allocation engine's ranking so the HOD "pending" view and the engine
    agree on who gets allocated first.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        Unallocated ``Student`` rows sorted by ``success_score`` priority.
    """
    students = (
        db.query(Student)
        .filter(Student.mentor_id.is_(None))
        .all()
    )
    return sorted(students, key=_student_score_sort_key)


def get_mentors_by_department(db: Session) -> dict[str, list[Mentor]]:
    """Return all mentors grouped by ``department``.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        Mapping of department name to mentor ORM instances.
    """
    mentors_by_department: dict[str, list[Mentor]] = {}
    for mentor in db.query(Mentor).all():
        mentors_by_department.setdefault(mentor.department, []).append(mentor)
    return mentors_by_department


def get_workload_map(db: Session) -> dict[int, int]:
    """Return current mentee counts keyed by ``mentor.id``.

    Counts are derived from ``Student.mentor_id`` — the live roster FK.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        Mapping of ``mentor_id`` to number of assigned students.
    """
    rows = (
        db.query(Student.mentor_id, func.count(Student.id))
        .filter(Student.mentor_id.isnot(None))
        .group_by(Student.mentor_id)
        .all()
    )
    return {mentor_id: count for mentor_id, count in rows}


def commit_allocation_plan(
    db: Session,
    plan: list[tuple[int, int]],
    triggered_by_user_id: int,
    method: str = "auto",
) -> int:
    """Apply an allocation plan in a single transaction.

    Updates ``Student.mentor_id`` and inserts ``Allocation`` audit rows.

    Args:
        db: Active SQLAlchemy session.
        plan: ``(student_id, mentor_id)`` pairs produced by the engine.
        triggered_by_user_id: ``users.id`` of the user who triggered the run.
        method: Allocation method label (``"auto"`` or ``"manual"``).

    Returns:
        Number of allocations committed.

    Raises:
        Exception: Re-raised after ``db.rollback()`` on any failure.
    """
    try:
        now = datetime.now(timezone.utc)
        for student_id, mentor_id in plan:
            student = (
                db.query(Student)
                .filter(Student.id == student_id)
                .first()
            )
            if student is not None:
                student.mentor_id = mentor_id

            existing_allocation = (
                db.query(Allocation)
                .filter(Allocation.student_id == student_id)
                .first()
            )
            if existing_allocation is not None:
                existing_allocation.mentor_id = mentor_id
                existing_allocation.allocated_at = now
                existing_allocation.allocated_by = triggered_by_user_id
                existing_allocation.method = method
            else:
                db.add(
                    Allocation(
                        student_id=student_id,
                        mentor_id=mentor_id,
                        allocated_at=now,
                        allocated_by=triggered_by_user_id,
                        method=method,
                    )
                )

        db.commit()
        return len(plan)
    except Exception:
        db.rollback()
        raise


def reset_all_allocations(db: Session) -> int:
    """Clear all allocation records and reset ``Student.mentor_id`` to NULL.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        Number of allocation rows deleted.

    Raises:
        Exception: Re-raised after ``db.rollback()`` on any failure.
    """
    try:
        count = db.query(Allocation).count()
        db.query(Allocation).delete(synchronize_session=False)
        db.query(Student).update(
            {Student.mentor_id: None},
            synchronize_session=False,
        )
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise


def get_all_allocations(db: Session) -> list[Allocation]:
    """Return all allocation records with related student and mentor loaded.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        ``Allocation`` rows with ``student`` and ``mentor`` relationships eager-loaded.
    """
    return (
        db.query(Allocation)
        .options(
            joinedload(Allocation.student),
            joinedload(Allocation.mentor),
        )
        .all()
    )


def get_allocation_stats(db: Session) -> dict[str, Any]:
    """Return raw allocation counts for the statistics service.

    Uses ``Student.mentor_id`` as the source of truth for allocated vs pending.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        Dict with top-level totals and a per-department breakdown.
    """
    students = db.query(Student).all()
    mentors = db.query(Mentor).all()

    by_department: dict[str, dict[str, int]] = {}

    def _dept_bucket(department: str) -> dict[str, int]:
        if department not in by_department:
            by_department[department] = {
                "total_students": 0,
                "total_mentors": 0,
                "allocated": 0,
                "pending": 0,
            }
        return by_department[department]

    for student in students:
        bucket = _dept_bucket(student.department)
        bucket["total_students"] += 1
        if student.mentor_id is not None:
            bucket["allocated"] += 1
        else:
            bucket["pending"] += 1

    for mentor in mentors:
        _dept_bucket(mentor.department)["total_mentors"] += 1

    allocated = sum(1 for student in students if student.mentor_id is not None)

    return {
        "total_students": len(students),
        "total_mentors": len(mentors),
        "allocated": allocated,
        "pending": len(students) - allocated,
        "by_department": by_department,
    }
