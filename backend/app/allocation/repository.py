"""Database access layer for the allocation module."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from backend.app.allocation.models import Allocation
from backend.app.models.mentor import Mentor
from backend.app.models.student import Student


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
    return (
        db.query(Student)
        .filter(Student.mentor_id.is_(None))
        .order_by(Student.success_score.desc().nullslast(), Student.id)
        .all()
    )


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


def _merge_mentor_counts(
    by_department: dict[str, dict[str, int]],
    mentor_rows: list[tuple[str, int]],
) -> None:
    """Fill in ``total_mentors`` for each department from query rows.

    Departments with students but no mentors get a zero count.
    Departments with mentors have their count added to the existing entry.
    """
    for dept, total_mentors in mentor_rows:
        if dept not in by_department:
            by_department[dept] = {
                "total_students": 0,
                "total_mentors": total_mentors,
                "allocated": 0,
                "pending": 0,
            }
        else:
            by_department[dept]["total_mentors"] = total_mentors


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
    if not plan:
        return 0

    try:
        now = datetime.now(timezone.utc)
        student_ids = [s for s, _ in plan]
        mentor_by_student = {s: m for s, m in plan}

        # Fetch students once and update
        students = (
            db.query(Student)
            .filter(Student.id.in_(student_ids))
            .all()
        )
        for student in students:
            student.mentor_id = mentor_by_student[student.id]

        # Bulk insert Allocation rows
        allocations_data = [
            {
                "student_id": s,
                "mentor_id": m,
                "allocated_at": now,
                "allocated_by": triggered_by_user_id,
                "method": method,
            }
            for s, m in plan
        ]
        db.bulk_insert_mappings(Allocation, allocations_data)

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
    Computed in SQL via aggregation — no full-table scans in Python.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        Dict with top-level totals and a per-department breakdown.
    """
    total_students = db.query(func.count(Student.id)).scalar()
    total_mentors = db.query(func.count(Mentor.id)).scalar()
    allocated = (
        db.query(func.count(Student.id))
        .filter(Student.mentor_id.isnot(None))
        .scalar()
    )
    pending = total_students - allocated

    # Per-department breakdown from SQL aggregation
    dept_rows = (
        db.query(
            Student.department,
            func.count(Student.id).label("total_students"),
            func.count(Student.mentor_id).label("allocated"),
        )
        .group_by(Student.department)
        .all()
    )

    mentor_rows = (
        db.query(Mentor.department, func.count(Mentor.id))
        .group_by(Mentor.department)
        .all()
    )

    by_department: dict[str, dict[str, int]] = {}
    for dept, total_dept_students, dept_allocated in dept_rows:
        by_department[dept] = {
            "total_students": total_dept_students,
            "total_mentors": 0,
            "allocated": dept_allocated,
            "pending": total_dept_students - dept_allocated,
        }

    _merge_mentor_counts(by_department, mentor_rows)

    return {
        "total_students": total_students,
        "total_mentors": total_mentors,
        "allocated": allocated,
        "pending": pending,
        "by_department": by_department,
    }