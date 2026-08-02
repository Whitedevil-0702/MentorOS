"""SQLAlchemy model for the allocations audit table."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from backend.app.core.database import Base


def _utc_now() -> datetime:
    """Return the current UTC timestamp for allocation audit records."""
    return datetime.now(timezone.utc)


class Allocation(Base):
    """Records a mentor assignment event for a student.

    The live roster FK lives on ``Student.mentor_id``; this table is an
    audit log of who was assigned, when, and by which method.
    """

    __tablename__ = "allocations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(
        Integer,
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    mentor_id = Column(
        Integer,
        ForeignKey("mentors.id", ondelete="CASCADE"),
        nullable=False,
    )
    allocated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )
    allocated_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    method = Column(String(20), nullable=False, default="auto")

    student = relationship("Student", foreign_keys=[student_id])
    mentor = relationship("Mentor", foreign_keys=[mentor_id])

    def __repr__(self) -> str:
        return (
            f"<Allocation(id={self.id}, student_id={self.student_id}, "
            f"mentor_id={self.mentor_id}, method={self.method!r})>"
        )
