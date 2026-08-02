"""Dev-only seeding and role promotion for the allocation module.

Roles are DB-backed (``User.role``) in this codebase — never client-supplied —
so promoting a signed-in Supabase user is done server-side here, matching how
``require_role()`` and the admin ``change_role`` action work.

Usage (run from ``backend/`` so ``.env`` is found):

    python -m scripts.seed_allocation --promote you@example.com --role HOD
    python -m scripts.seed_allocation --data

``--promote`` promotes an existing user (matched by email or ``supabase_user_id``).
``--data`` idempotently creates mentors + unallocated students per department.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import func

from backend.app.core.database import SessionLocal
from backend.app.models.mentor import Mentor
from backend.app.models.student import Student
from backend.app.models.user import User, UserRole

# Department -> (mentor_count, max_mentees, student_count)
DEPT_PLAN: dict[str, tuple[int, int, int]] = {
    "CSE": (3, 5, 12),
    "ECE": (2, 4, 8),
    "ME": (2, 3, 6),
}

SCORES = [95.0, 88.0, 76.0, 64.0, 55.0, 41.0, 33.0, 22.0]


def _role(value: str) -> UserRole:
    normalized = value.strip().lower()
    for role in UserRole:
        if role.value.lower() == normalized or role.name.lower() == normalized:
            return role
    raise SystemExit(f"Invalid role '{value}'. Use one of: {[r.value for r in UserRole]}")


def promote(db, email: str, role: UserRole) -> None:
    user = db.query(User).filter(func.lower(User.email) == email.lower()).first()
    if user is None:
        user = db.query(User).filter(User.supabase_user_id == email).first()
    if user is None:
        raise SystemExit(f"No user found for '{email}'. Sign in once via the app first.")
    user.role = role
    db.commit()
    print(f"Promoted {user.email} (id={user.id}) to {role.value}")


def seed_data(db) -> None:
    total_students = 0
    total_mentors = 0
    for dept, (mentor_count, max_mentees, student_count) in DEPT_PLAN.items():
        existing_mentors = db.query(Mentor).filter(Mentor.department == dept).count()
        for i in range(existing_mentors, mentor_count):
            email = f"mentor.{dept.lower()}.{i}@mentoros.dev"
            user = User(email=email, full_name=f"{dept} Mentor {i}", role=UserRole.MENTOR, is_active=True)
            db.add(user)
            db.flush()
            db.add(Mentor(user_id=user.id, department=dept, max_mentees=max_mentees))
            total_mentors += 1

        existing_students = db.query(Student).filter(Student.department == dept).count()
        for i in range(existing_students, student_count):
            usn = f"{dept}{i:03d}"
            email = f"student.{dept.lower()}.{i}@mentoros.dev"
            user = User(email=email, full_name=usn, role=UserRole.STUDENT, is_active=True)
            db.add(user)
            db.flush()
            score = SCORES[i % len(SCORES)]
            risk = "Green" if score >= 70 else "Amber" if score >= 50 else "Coral"
            db.add(
                Student(
                    user_id=user.id,
                    usn=usn,
                    department=dept,
                    semester=5,
                    success_score=score,
                    risk_status=risk,
                    mentor_id=None,
                )
            )
            total_students += 1

    db.commit()
    print(f"Seeded {total_mentors} mentors and {total_students} unallocated students.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed/promote allocation test data.")
    parser.add_argument("--promote", metavar="EMAIL_OR_SUPABASE_ID", help="Promote a user to a role.")
    parser.add_argument("--role", default="HOD", help="Role to promote to (default: HOD).")
    parser.add_argument("--data", action="store_true", help="Create mentors + unallocated students.")
    args = parser.parse_args()

    if not args.promote and not args.data:
        parser.print_help()
        raise SystemExit(1)

    db = SessionLocal()
    try:
        if args.promote:
            promote(db, args.promote, _role(args.role))
        if args.data:
            seed_data(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
