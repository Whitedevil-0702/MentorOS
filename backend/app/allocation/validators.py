"""Pre-flight validation helpers for the allocation module."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.allocation.exceptions import (
    DepartmentMismatchError,
    NoMentorCapacityError,
    NoPendingStudentsError,
)
from backend.app.models.mentor import Mentor
from backend.app.models.student import Student


def validate_has_pending_students(db: Session) -> None:
    """Raise ``NoPendingStudentsError`` if no unallocated students exist.

    Args:
        db: Active SQLAlchemy session.

    Raises:
        NoPendingStudentsError: When every student already has a mentor assigned.
    """
    has_unallocated = (
        db.query(Student.id).filter(Student.mentor_id.is_(None)).first()
    )
    if has_unallocated is None:
        raise NoPendingStudentsError()


def validate_mentor_capacity(mentor: Mentor, current_count: int) -> None:
    """Raise ``NoMentorCapacityError`` if the mentor is at maximum capacity.

    Args:
        mentor: Mentor ORM instance whose capacity is being checked.
        current_count: Number of students currently assigned to the mentor.

    Raises:
        NoMentorCapacityError: When ``current_count`` is at or above ``max_mentees``.
    """
    is_at_capacity = current_count >= mentor.max_mentees
    if is_at_capacity:
        raise NoMentorCapacityError(
            f"Mentor {mentor.id} is at maximum capacity ({mentor.max_mentees})"
        )


def validate_same_department(student: Student, mentor: Mentor) -> None:
    """Raise ``DepartmentMismatchError`` if student and mentor departments differ.

    Args:
        student: Student ORM instance to validate.
        mentor: Mentor ORM instance to validate.

    Raises:
        DepartmentMismatchError: When ``student.department`` != ``mentor.department``.
    """
    departments_match = student.department == mentor.department
    if not departments_match:
        raise DepartmentMismatchError(
            f"Department mismatch: student ({student.department}) "
            f"vs mentor ({mentor.department})"
        )