"""
Real Student Success Score computation (Phase 3 — SGPA variant).

    Total = 0.35*Attendance + 0.35*Academic + 0.15*Engagement + 0.15*Placement

Academic uses SGPA (this semester), not CGPA. Attendance and Academic are the
two pillars: if either has no source data the result is `insufficient_data`
(score = None) rather than a misleading number. This module has no Celery
dependency so it stays importable/testable on its own.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.student import Student
from backend.app.models.academic import (
    AttendanceRecord,
    LmsActivityRecord,
    PlacementProfile,
    StudentSuccessScore,
)

DEFAULT_PERIOD = settings.SCORING_PERIOD

# Single source of truth for the four component weights. The allocation engine
# imports this so "how we score" and "how we rank for allocation" stay in sync.
COMPONENT_WEIGHTS = {
    "attendance": 0.35,
    "academic": 0.35,
    "engagement": 0.15,
    "placement": 0.15,
}

# Mirror the new lowercase risk taxonomy onto the existing capitalised
# `students.risk_status` so current NAAC/compliance endpoints don't regress.
RISK_STATUS_MIRROR = {
    "green": "Green",
    "amber": "Amber",
    "coral": "Coral",
    "insufficient_data": "Insufficient",
}


class ScoringEngine:
    """Compute the Success Score from attendance, SGPA, LMS and placement data."""

    def __init__(self, db: Session):
        self.db = db
        # Cache of avg LMS logins per (department, period). Computed once and
        # reused across students in a batch — avoids an aggregate query per
        # student in the nightly recompute.
        self._cohort_cache: dict = {}

    # ----- components -----------------------------------------------------

    def attendance_component(self, student_id: int, period: str) -> Optional[float]:
        """mean(attended/total × 100) across subjects; None if no records."""
        records = (
            self.db.query(AttendanceRecord)
            .filter(
                AttendanceRecord.student_id == student_id,
                AttendanceRecord.period == period,
            )
            .all()
        )
        if not records:
            return None
        percentages = [
            (r.attended_classes / r.total_classes * 100) if r.total_classes > 0 else 0
            for r in records
        ]
        return sum(percentages) / len(percentages)

    def academic_component(self, student_id: int) -> Optional[float]:
        """min(SGPA × 10, 100); None if SGPA not available. SGPA, not CGPA."""
        student = self.db.query(Student).filter(Student.id == student_id).first()
        if not student or student.sgpa is None:
            return None
        return min(student.sgpa * 10, 100)

    def _cohort_avg_logins(self, department: Optional[str], period: str) -> float:
        """Average LMS logins for the student's cohort (same department + period)."""
        key = (department, period)
        if key not in self._cohort_cache:
            q = (
                self.db.query(func.avg(LmsActivityRecord.login_count))
                .join(Student, LmsActivityRecord.student_id == Student.id)
                .filter(LmsActivityRecord.period == period)
            )
            if department is not None:
                q = q.filter(Student.department == department)
            self._cohort_cache[key] = q.scalar() or 1
        return self._cohort_cache[key]

    def engagement_component(self, student_id: int, period: str) -> Optional[float]:
        """
        ((login_normalised + submission_rate) / 2); None if no LMS record.
        login_normalised = (logins / cohort_avg) × 100 capped at 100.
        Cohort average is scoped to the student's department for the period.
        """
        record = (
            self.db.query(LmsActivityRecord)
            .filter(
                LmsActivityRecord.student_id == student_id,
                LmsActivityRecord.period == period,
            )
            .first()
        )
        if not record or (
            record.login_count == 0 and record.assignments_submitted == 0
        ):
            return None

        student = self.db.query(Student).filter(Student.id == student_id).first()
        department = student.department if student else None
        cohort_avg = self._cohort_avg_logins(department, period)
        login_normalised = min((record.login_count / cohort_avg) * 100, 100)

        submission_rate = (
            (record.assignments_submitted / record.assignments_total * 100)
            if record.assignments_total > 0
            else 0
        )
        return (login_normalised + submission_rate) / 2

    def placement_component(self, student_id: int) -> float:
        """resume(40) + min(skills,5)×8 + min(certs,5)×4; 0.0 if no profile."""
        profile = (
            self.db.query(PlacementProfile)
            .filter(PlacementProfile.student_id == student_id)
            .first()
        )
        if not profile:
            return 0.0
        score = 0.0
        if profile.has_resume:
            score += 40
        score += min(profile.skills_count, 5) * 8
        score += min(profile.certifications_count, 5) * 4
        return min(score, 100.0)

    # ----- aggregation ----------------------------------------------------

    def compute_success_score(self, student_id: int, period: str = DEFAULT_PERIOD) -> dict:
        att = self.attendance_component(student_id, period)
        acad = self.academic_component(student_id)
        eng = self.engagement_component(student_id, period)
        place = self.placement_component(student_id)

        if att is None or acad is None:
            total_score: Optional[float] = None
            risk_category = "insufficient_data"
        else:
            eng_w = eng if eng is not None else 0
            place_w = place if place is not None else 0
            total_score = round(
                (COMPONENT_WEIGHTS["attendance"] * att)
                + (COMPONENT_WEIGHTS["academic"] * acad)
                + (COMPONENT_WEIGHTS["engagement"] * eng_w)
                + (COMPONENT_WEIGHTS["placement"] * place_w),
                2,
            )
            if total_score >= 70:
                risk_category = "green"
            elif total_score >= 50:
                risk_category = "amber"
            else:
                risk_category = "coral"

        return {
            "student_id": student_id,
            "period": period,
            "attendance_component": att,
            "academic_component": acad,
            "engagement_component": eng,
            "placement_component": place,
            "total_score": total_score,
            "risk_category": risk_category,
        }

    # ----- persistence ----------------------------------------------------

    def store_score(self, student_id: int, period: str = DEFAULT_PERIOD) -> dict:
        """Compute one student's score, append a history row, mirror to students."""
        data = self.compute_success_score(student_id, period)

        self.db.add(
            StudentSuccessScore(
                student_id=student_id,
                attendance_component=data["attendance_component"],
                academic_component=data["academic_component"],
                engagement_component=data["engagement_component"],
                placement_component=data["placement_component"],
                total_score=data["total_score"],
                risk_category=data["risk_category"],
                period=period,
                computed_at=datetime.now(timezone.utc),
            )
        )

        student = self.db.query(Student).filter(Student.id == student_id).first()
        if student:
            student.success_score = data["total_score"]
            student.risk_status = RISK_STATUS_MIRROR.get(
                data["risk_category"], student.risk_status
            )
        self.db.commit()
        return data


def recompute_and_store(db: Session, period: str = DEFAULT_PERIOD) -> int:
    """Synchronously (re)compute + persist scores for all students. Returns count."""
    engine = ScoringEngine(db)
    students = db.query(Student.id).all()
    count = 0
    for (student_id,) in students:
        engine.store_score(student_id, period)
        count += 1
    return count
