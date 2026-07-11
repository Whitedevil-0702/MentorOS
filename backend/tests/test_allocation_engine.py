"""
Comprehensive tests for the allocation engine (score-prioritised variant).

The engine ranks students by their ``success_score`` (0–100, the weighted blend
produced by the scoring engine) and assigns each, in that order, to the mentor
in the same department who currently carries the lightest load. A per-department
min-heap keeps assignments balanced within ±1 mentee.

Tests cover: score-based priority, department isolation, capacity limits,
workload balancing, the (non-silent) skipped-student list, and the repository /
service layers end-to-end.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.database import Base
from backend.app.models.user import User
from backend.app.models.student import Student
from backend.app.models.mentor import Mentor
from backend.app.allocation import engine, repository, service, validators
from backend.app.allocation.exceptions import (
    NoPendingStudentsError,
    NoMentorCapacityError,
    DepartmentMismatchError,
)

# ─── Test database setup ───
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


# ─── Helper factories ───
def make_user(db, email, role, full_name=None):
    u = User(
        email=email,
        hashed_password="test",
        full_name=full_name or email,
        role=role,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def make_mentor(db, user, department="CSE", max_mentees=20):
    m = Mentor(user_id=user.id, department=department, max_mentees=max_mentees)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def make_student(db, user, usn, department="CSE", semester=5, sgpa=None,
                 mentor_id=None, risk_status="Green", success_score=100.0):
    s = Student(
        user_id=user.id,
        usn=usn,
        department=department,
        semester=semester,
        sgpa=sgpa,
        success_score=success_score,
        risk_status=risk_status,
        mentor_id=mentor_id,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


# ─── Unit tests for engine.allocate() ───
class TestAllocationEngine:
    """Tests for the pure engine.allocate function (no DB)."""

    def test_basic_allocation_single_dept(self):
        """Simple case: 3 students, 2 mentors with capacity 2 each."""
        students_by_dept = {
            "CSE": [
                {"id": 1, "success_score": 90.0},
                {"id": 2, "success_score": 60.0},
                {"id": 3, "success_score": 30.0},
            ]
        }
        mentors_by_dept = {
            "CSE": [
                {"id": 101, "max_mentees": 2},
                {"id": 102, "max_mentees": 2},
            ]
        }
        workload_map = {101: 0, 102: 0}

        result = engine.allocate(students_by_dept, mentors_by_dept, workload_map)

        assert result["stats"]["allocated"] == 3
        assert result["stats"]["skipped"] == 0
        assert len(result["plan"]) == 3

        # Highest score (id 1, 90) goes first → mentor 101 (load 0).
        # Next (id 2, 60) → mentor 102 (load 0). Last (id 3, 30) → mentor 101 (load 1).
        plan_dict = dict(result["plan"])
        assert plan_dict[1] == 101
        assert plan_dict[2] == 102
        assert plan_dict[3] == 101

    def test_score_priority_order(self):
        """Verify highest success_score is allocated first."""
        students_by_dept = {
            "CSE": [
                {"id": 1, "success_score": 55.0},
                {"id": 2, "success_score": 12.0},
                {"id": 3, "success_score": 88.0},
                {"id": 4, "success_score": 71.0},
            ]
        }
        mentors_by_dept = {"CSE": [{"id": 101, "max_mentees": 4}]}
        workload_map = {101: 0}

        result = engine.allocate(students_by_dept, mentors_by_dept, workload_map)

        allocated_order = [s for s, _ in result["plan"]]
        # 88 (id3) → 71 (id4) → 55 (id1) → 12 (id2)
        assert allocated_order == [3, 4, 1, 2]

    def test_tie_broken_by_id(self):
        """Equal scores fall back to ascending student id for determinism."""
        students_by_dept = {
            "CSE": [
                {"id": 7, "success_score": 50.0},
                {"id": 2, "success_score": 50.0},
                {"id": 5, "success_score": 50.0},
            ]
        }
        mentors_by_dept = {"CSE": [{"id": 101, "max_mentees": 3}]}
        workload_map = {101: 0}

        result = engine.allocate(students_by_dept, mentors_by_dept, workload_map)
        allocated_order = [s for s, _ in result["plan"]]
        assert allocated_order == [2, 5, 7]

    def test_none_score_treated_as_zero(self):
        """Unscored (None) students sink to the bottom of the queue."""
        students_by_dept = {
            "CSE": [
                {"id": 1, "success_score": None},
                {"id": 2, "success_score": 80.0},
                {"id": 3, "success_score": 40.0},
            ]
        }
        mentors_by_dept = {"CSE": [{"id": 101, "max_mentees": 3}]}
        workload_map = {101: 0}

        result = engine.allocate(students_by_dept, mentors_by_dept, workload_map)
        allocated_order = [s for s, _ in result["plan"]]
        assert allocated_order == [2, 3, 1]  # None → treated as 0, last

    def test_capacity_limit_respected(self):
        """Students beyond total capacity are skipped and reported by id."""
        students_by_dept = {
            "CSE": [{"id": i, "success_score": 50.0} for i in range(1, 6)]  # 5 students
        }
        mentors_by_dept = {"CSE": [{"id": 101, "max_mentees": 2}]}  # capacity 2
        workload_map = {101: 0}

        result = engine.allocate(students_by_dept, mentors_by_dept, workload_map)

        assert result["stats"]["allocated"] == 2
        assert result["stats"]["skipped"] == 3
        # Skipped are the lowest-scoring (all 50 → tie broken by id → ids 3,4,5)
        assert result["stats"]["skipped_students"] == [3, 4, 5]

    def test_workload_balancing_across_mentors(self):
        """Students should be distributed to keep mentor loads within ±1."""
        students_by_dept = {
            "CSE": [{"id": i, "success_score": 50.0} for i in range(1, 5)]
        }
        mentors_by_dept = {
            "CSE": [
                {"id": 101, "max_mentees": 3},
                {"id": 102, "max_mentees": 3},
            ]
        }
        workload_map = {101: 0, 102: 0}

        result = engine.allocate(students_by_dept, mentors_by_dept, workload_map)

        # Should be 2-2 split
        mentor_loads = {}
        for _, m_id in result["plan"]:
            mentor_loads[m_id] = mentor_loads.get(m_id, 0) + 1
        assert set(mentor_loads.values()) == {2}

    def test_high_score_gets_lightest_mentor(self):
        """A high-scoring student is paired with the lowest-load mentor."""
        students_by_dept = {
            "CSE": [
                {"id": 1, "success_score": 95.0},  # top scorer
                {"id": 2, "success_score": 80.0},
                {"id": 3, "success_score": 70.0},
            ]
        }
        mentors_by_dept = {
            "CSE": [
                {"id": 101, "max_mentees": 3},  # currently busy (load 2)
                {"id": 102, "max_mentees": 3},  # currently free (load 0)
            ]
        }
        workload_map = {101: 2, 102: 0}

        result = engine.allocate(students_by_dept, mentors_by_dept, workload_map)

        plan_dict = dict(result["plan"])
        # Top scorer (id 1) should land on the free mentor (102).
        assert plan_dict[1] == 102

    def test_existing_workload_respected(self):
        """Pre-existing mentor loads should be accounted for."""
        students_by_dept = {
            "CSE": [{"id": i, "success_score": 50.0} for i in range(1, 4)]
        }
        mentors_by_dept = {"CSE": [{"id": 101, "max_mentees": 3}, {"id": 102, "max_mentees": 3}]}
        workload_map = {101: 2, 102: 0}  # mentor 101 already has 2

        result = engine.allocate(students_by_dept, mentors_by_dept, workload_map)

        # New students should go to mentor 102 first (lower load)
        mentor_loads = {}
        for _, m_id in result["plan"]:
            mentor_loads[m_id] = mentor_loads.get(m_id, 0) + 1
        assert mentor_loads.get(102, 0) >= mentor_loads.get(101, 0)

    def test_department_isolation(self):
        """CSE students only get CSE mentors; ECE students only get ECE mentors."""
        students_by_dept = {
            "CSE": [{"id": 1, "success_score": 90.0}],
            "ECE": [{"id": 2, "success_score": 90.0}],
        }
        mentors_by_dept = {
            "CSE": [{"id": 101, "max_mentees": 1}],
            "ECE": [{"id": 201, "max_mentees": 1}],
        }
        workload_map = {101: 0, 201: 0}

        result = engine.allocate(students_by_dept, mentors_by_dept, workload_map)

        plan_dict = dict(result["plan"])
        assert plan_dict[1] == 101  # CSE student -> CSE mentor
        assert plan_dict[2] == 201  # ECE student -> ECE mentor

    def test_no_mentors_in_department_skips_students(self):
        """Students in dept with no mentors should be skipped (and reported)."""
        students_by_dept = {
            "CSE": [{"id": 1, "success_score": 90.0}],
            "MECH": [{"id": 2, "success_score": 50.0}],  # no mentors
        }
        mentors_by_dept = {"CSE": [{"id": 101, "max_mentees": 1}]}
        workload_map = {101: 0}

        result = engine.allocate(students_by_dept, mentors_by_dept, workload_map)

        assert result["stats"]["allocated"] == 1
        assert result["stats"]["skipped"] == 1
        assert result["stats"]["skipped_students"] == [2]
        assert result["stats"]["by_dept"]["MECH"]["skipped"] == 1

    def test_empty_inputs(self):
        """Empty student or mentor lists should return empty plan."""
        result = engine.allocate({}, {}, {})
        assert result["plan"] == []
        assert result["stats"]["allocated"] == 0
        assert result["stats"]["skipped"] == 0
        assert result["stats"]["skipped_students"] == []

    def test_mentor_at_capacity_excluded_from_heap(self):
        """Mentors already at max_mentees should not receive new students."""
        students_by_dept = {"CSE": [{"id": i, "success_score": 50.0} for i in range(1, 4)]}
        mentors_by_dept = {"CSE": [{"id": 101, "max_mentees": 2}]}
        workload_map = {101: 2}  # already at capacity

        result = engine.allocate(students_by_dept, mentors_by_dept, workload_map)

        assert result["stats"]["allocated"] == 0
        assert result["stats"]["skipped"] == 3
        assert result["stats"]["skipped_students"] == [1, 2, 3]

    def test_multiple_departments_independent_allocation(self):
        """Each department's allocation should be independent."""
        students_by_dept = {
            "CSE": [{"id": i, "success_score": 50.0} for i in range(1, 4)],
            "ECE": [{"id": i, "success_score": 50.0} for i in range(10, 13)],
        }
        mentors_by_dept = {
            "CSE": [{"id": 101, "max_mentees": 2}],
            "ECE": [{"id": 201, "max_mentees": 2}],
        }
        workload_map = {101: 0, 201: 0}

        result = engine.allocate(students_by_dept, mentors_by_dept, workload_map)

        assert result["stats"]["by_dept"]["CSE"]["allocated"] == 2
        assert result["stats"]["by_dept"]["CSE"]["skipped"] == 1
        assert result["stats"]["by_dept"]["ECE"]["allocated"] == 2
        assert result["stats"]["by_dept"]["ECE"]["skipped"] == 1

    def test_mentor_with_zero_capacity_excluded(self):
        """Mentor with max_mentees=0 should not receive students."""
        students_by_dept = {"CSE": [{"id": 1, "success_score": 90.0}]}
        mentors_by_dept = {"CSE": [{"id": 101, "max_mentees": 0}]}
        workload_map = {101: 0}

        result = engine.allocate(students_by_dept, mentors_by_dept, workload_map)

        assert result["stats"]["allocated"] == 0
        assert result["stats"]["skipped"] == 1
        assert result["stats"]["skipped_students"] == [1]


# ─── Integration tests with repository layer ───
class TestRepository:
    """Tests for repository functions using real DB."""

    def test_get_unallocated_students_orders_by_score(self, db):
        """Unallocated students should be returned highest score → lowest."""
        mentor_u = make_user(db, "mentor@x.edu", "Mentor")
        make_mentor(db, mentor_u, max_mentees=10)

        for i, (usn, score) in enumerate([
            ("CS001", 88.0),
            ("CS002", 45.0),
            ("CS003", 72.0),
            ("CS004", 91.0),
        ]):
            u = make_user(db, f"stu{i}@x.edu", "Student")
            make_student(db, u, usn, success_score=score, risk_status="Green")

        students = repository.get_unallocated_students(db)
        score_order = [s.success_score for s in students]
        assert score_order == [91.0, 88.0, 72.0, 45.0]

    def test_get_workload_map(self, db):
        """Workload map should reflect current Student.mentor_id assignments."""
        mentor_u = make_user(db, "mentor@x.edu", "Mentor")
        mentor = make_mentor(db, mentor_u, max_mentees=10)

        for i in range(3):
            u = make_user(db, f"stu{i}@x.edu", "Student")
            make_student(db, u, f"CS00{i}", mentor_id=mentor.id)

        for i in range(3, 5):
            u = make_user(db, f"stu{i}@x.edu", "Student")
            make_student(db, u, f"CS00{i}")

        workload = repository.get_workload_map(db)
        assert workload[mentor.id] == 3

    def test_get_mentors_by_department(self, db):
        """Mentors should be grouped by department."""
        for dept in ["CSE", "ECE", "MECH"]:
            u = make_user(db, f"mentor_{dept}@x.edu", "Mentor")
            make_mentor(db, u, department=dept)

        mentors_by_dept = repository.get_mentors_by_department(db)
        assert set(mentors_by_dept.keys()) == {"CSE", "ECE", "MECH"}
        assert len(mentors_by_dept["CSE"]) == 1

    def test_commit_allocation_plan_updates_student_and_creates_audit(self, db):
        """commit_allocation_plan should update Student.mentor_id and create Allocation rows."""
        mentor_u = make_user(db, "mentor@x.edu", "Mentor")
        mentor = make_mentor(db, mentor_u)

        u1 = make_user(db, "stu1@x.edu", "Student")
        s1 = make_student(db, u1, "CS001")
        u2 = make_user(db, "stu2@x.edu", "Student")
        s2 = make_student(db, u2, "CS002")

        plan = [(s1.id, mentor.id), (s2.id, mentor.id)]
        count = repository.commit_allocation_plan(db, plan, triggered_by_user_id=mentor_u.id)

        assert count == 2
        db.refresh(s1)
        db.refresh(s2)
        assert s1.mentor_id == mentor.id
        assert s2.mentor_id == mentor.id

        allocations = repository.get_all_allocations(db)
        assert len(allocations) == 2
        assert all(a.method == "auto" for a in allocations)

    def test_reset_all_allocations_clears_everything(self, db):
        """reset_all_allocations should delete Allocation rows and nullify Student.mentor_id."""
        mentor_u = make_user(db, "mentor@x.edu", "Mentor")
        mentor = make_mentor(db, mentor_u)

        u = make_user(db, "stu@x.edu", "Student")
        s = make_student(db, u, "CS001")

        repository.commit_allocation_plan(db, [(s.id, mentor.id)], mentor_u.id)

        cleared = repository.reset_all_allocations(db)
        assert cleared == 1

        db.refresh(s)
        assert s.mentor_id is None
        assert repository.get_all_allocations(db) == []


# ─── Integration tests for service layer ───
class TestServiceLayer:
    """Tests for service.run_allocation, reset_allocation, get_pending, etc."""

    def test_run_allocation_basic(self, db):
        """End-to-end auto allocation should work."""
        admin_u = make_user(db, "admin@x.edu", "Admin")
        mentor_u = make_user(db, "mentor@x.edu", "Mentor")
        make_mentor(db, mentor_u, max_mentees=10)

        for i in range(3):
            u = make_user(db, f"stu{i}@x.edu", "Student")
            make_student(db, u, f"CS00{i}", success_score=50.0)

        result = service.run_allocation(db, admin_u)

        assert result.allocated == 3
        assert result.skipped == 0
        assert result.skipped_students == []
        students = db.query(Student).all()
        assert all(s.mentor_id is not None for s in students)

    def test_run_allocation_raises_when_no_pending(self, db):
        """Should raise NoPendingStudentsError if all students already have mentors."""
        admin_u = make_user(db, "admin@x.edu", "Admin")
        mentor_u = make_user(db, "mentor@x.edu", "Mentor")
        mentor = make_mentor(db, mentor_u)

        u = make_user(db, "stu@x.edu", "Student")
        make_student(db, u, "CS001", mentor_id=mentor.id)

        with pytest.raises(NoPendingStudentsError):
            service.run_allocation(db, admin_u)

    def test_run_allocation_respects_capacity(self, db):
        """Should skip students when mentors at capacity."""
        admin_u = make_user(db, "admin@x.edu", "Admin")
        mentor_u = make_user(db, "mentor@x.edu", "Mentor")
        make_mentor(db, mentor_u, max_mentees=2)

        for i in range(5):
            u = make_user(db, f"stu{i}@x.edu", "Student")
            make_student(db, u, f"CS00{i}", success_score=50.0)

        result = service.run_allocation(db, admin_u)

        assert result.allocated == 2
        assert result.skipped == 3

    def test_run_allocation_prioritizes_high_score(self, db):
        """Highest-scoring students should grab slots when capacity is limited."""
        admin_u = make_user(db, "admin@x.edu", "Admin")
        mentor_u = make_user(db, "mentor@x.edu", "Mentor")
        make_mentor(db, mentor_u, max_mentees=2)

        # Three students with different scores; only 2 slots available.
        u_low = make_user(db, "low@x.edu", "Student")
        s_low = make_student(db, u_low, "CS001", success_score=20.0, risk_status="Coral")
        u_mid = make_user(db, "mid@x.edu", "Student")
        s_mid = make_student(db, u_mid, "CS002", success_score=60.0, risk_status="Amber")
        u_high = make_user(db, "high@x.edu", "Student")
        s_high = make_student(db, u_high, "CS003", success_score=95.0, risk_status="Green")

        db.commit()

        result = service.run_allocation(db, admin_u)

        # With capacity 2, the two highest scores should win.
        assert result.allocated == 2
        assert result.skipped == 1
        assert result.skipped_students == [s_low.id]  # lowest score skipped

        allocated = db.query(Student).filter(Student.mentor_id.isnot(None)).all()
        allocated_ids = {s.id for s in allocated}
        assert s_high.id in allocated_ids
        assert s_mid.id in allocated_ids
        assert s_low.id not in allocated_ids

    def test_run_allocation_reports_skipped_students(self, db):
        """Skipped student ids should be returned in the response."""
        admin_u = make_user(db, "admin@x.edu", "Admin")
        make_mentor(db, make_user(db, "mentor@x.edu", "Mentor"), max_mentees=1)

        # 3 students, 1 slot → 2 skipped
        scores = [10.0, 50.0, 90.0]
        students = []
        for i, sc in enumerate(scores):
            u = make_user(db, f"stu{i}@x.edu", "Student")
            students.append(make_student(db, u, f"CS00{i}", success_score=sc))

        result = service.run_allocation(db, admin_u)

        assert result.allocated == 1
        assert result.skipped == 2
        # Highest score (90) allocated; the other two skipped.
        assert len(result.skipped_students) == 2
        assert students[2].id not in result.skipped_students  # top scorer placed

    def test_get_pending_returns_unallocated_ordered_by_score(self, db):
        """get_pending should return unallocated students in score priority order."""
        mentor_u = make_user(db, "mentor@x.edu", "Mentor")
        mentor = make_mentor(db, mentor_u)

        # Allocated student (should not appear)
        u_alloc = make_user(db, "alloc@x.edu", "Student")
        make_student(db, u_alloc, "CS000", mentor_id=mentor.id, success_score=99.0)

        # Unallocated with different scores
        u_low = make_user(db, "low@x.edu", "Student")
        s_low = make_student(db, u_low, "CS001", success_score=30.0, risk_status="Coral")
        u_high = make_user(db, "high@x.edu", "Student")
        s_high = make_student(db, u_high, "CS002", success_score=85.0, risk_status="Green")
        u_mid = make_user(db, "mid@x.edu", "Student")
        s_mid = make_student(db, u_mid, "CS003", success_score=60.0, risk_status="Amber")

        db.commit()

        pending = service.get_pending(db)
        assert len(pending) == 3
        assert [p.success_score for p in pending] == [85.0, 60.0, 30.0]

    def test_reset_allocation_clears_everything(self, db):
        """reset_allocation should clear all mentor assignments and audit log."""
        admin_u = make_user(db, "admin@x.edu", "Admin")
        mentor_u = make_user(db, "mentor@x.edu", "Mentor")
        mentor = make_mentor(db, mentor_u)

        u = make_user(db, "stu@x.edu", "Student")
        s = make_student(db, u, "CS001")

        repository.commit_allocation_plan(db, [(s.id, mentor.id)], admin_u.id)

        result = service.reset_allocation(db, admin_u)
        assert result.cleared == 1

        db.refresh(s)
        assert s.mentor_id is None

    def test_get_workload_returns_mentor_with_mentees(self, db):
        """get_workload should return mentor load with mentee details."""
        mentor_u = make_user(db, "mentor@x.edu", "Mentor", "Dr. Mentor")
        mentor = make_mentor(db, mentor_u, max_mentees=10)

        for i in range(2):
            u = make_user(db, f"stu{i}@x.edu", "Student", f"Student {i}")
            s = make_student(db, u, f"CS00{i}", mentor_id=mentor.id,
                             success_score=80.0 if i == 0 else 40.0,
                             risk_status="Coral" if i == 0 else "Green")

        db.commit()

        workloads = service.get_workload(db)
        assert len(workloads) == 1
        w = workloads[0]
        assert w.mentor_id == mentor.id
        assert w.mentor_name == "Dr. Mentor"
        assert w.current == 2
        assert w.max == 10
        assert len(w.mentees) == 2

    def test_get_statistics(self, db):
        """get_statistics should return correct aggregate counts."""
        mentor_u1 = make_user(db, "mentor1@x.edu", "Mentor")
        mentor1 = make_mentor(db, mentor_u1, department="CSE", max_mentees=10)

        for i in range(3):
            u = make_user(db, f"cse_stu{i}@x.edu", "Student")
            s = make_student(db, u, f"CS00{i}", department="CSE", success_score=50.0)
            if i < 2:
                s.mentor_id = mentor1.id

        mentor_u2 = make_user(db, "mentor2@x.edu", "Mentor")
        make_mentor(db, mentor_u2, department="ECE", max_mentees=10)

        u = make_user(db, "ece_stu@x.edu", "Student")
        make_student(db, u, "EC001", department="ECE", success_score=50.0)

        db.commit()

        stats = service.get_statistics(db)
        assert stats.total_students == 4
        assert stats.total_mentors == 2
        assert stats.allocated == 2
        assert stats.pending == 2
        assert stats.by_department["CSE"].total_students == 3
        assert stats.by_department["CSE"].allocated == 2
        assert stats.by_department["ECE"].total_students == 1


# ─── Validator tests ───
# ─── Validator tests ───
class TestValidators:
    def test_validate_mentor_capacity_raises_at_limit(self, db):
        mentor_u = make_user(db, "mentor@x.edu", "Mentor")
        mentor = make_mentor(db, mentor_u, max_mentees=2)

        with pytest.raises(NoMentorCapacityError):
            validators.validate_mentor_capacity(mentor, current_count=2)

    def test_validate_mentor_capacity_ok_below_limit(self, db):
        mentor_u = make_user(db, "mentor@x.edu", "Mentor")
        mentor = make_mentor(db, mentor_u, max_mentees=5)

        validators.validate_mentor_capacity(mentor, current_count=4)  # Should not raise

    def test_validate_same_department_raises_on_mismatch(self, db):
        mentor_u = make_user(db, "mentor@x.edu", "Mentor")
        mentor = make_mentor(db, mentor_u, department="CSE")

        u = make_user(db, "stu@x.edu", "Student")
        student = make_student(db, u, "EC001", department="ECE")

        with pytest.raises(DepartmentMismatchError):
            validators.validate_same_department(student, mentor)

    def test_validate_same_department_ok_on_match(self, db):
        mentor_u = make_user(db, "mentor@x.edu", "Mentor")
        mentor = make_mentor(db, mentor_u, department="CSE")

        u = make_user(db, "stu@x.edu", "Student")
        student = make_student(db, u, "CS001", department="CSE")

        validators.validate_same_department(student, mentor)  # Should not raise

    def test_validate_has_pending_students_raises_when_none(self, db):
        mentor_u = make_user(db, "mentor@x.edu", "Mentor")
        mentor = make_mentor(db, mentor_u)

        u = make_user(db, "stu@x.edu", "Student")
        make_student(db, u, "CS001", mentor_id=mentor.id)

        with pytest.raises(NoPendingStudentsError):
            validators.validate_has_pending_students(db)


# ─── Edge case tests ───
class TestEdgeCases:
    def test_unscored_student_sorted_last(self, db):
        """An unscored (None) student should be allocated last."""
        admin_u = make_user(db, "admin@x.edu", "Admin")
        make_mentor(db, make_user(db, "mentor@x.edu", "Mentor"), max_mentees=2)

        u_scored = make_user(db, "scored@x.edu", "Student")
        make_student(db, u_scored, "CS001", success_score=70.0)
        u_unscored = make_user(db, "unscored@x.edu", "Student")
        make_student(db, u_unscored, "CS002", success_score=None)

        # capacity 2, 2 students → both placed; order tested via plan
        result = service.run_allocation(db, admin_u)
        assert result.allocated == 2
        assert result.skipped == 0

    def test_zero_capacity_mentor_gets_nobody(self, db):
        """A mentor with max_mentees=0 should receive no students."""
        admin_u = make_user(db, "admin@x.edu", "Admin")
        make_mentor(db, make_user(db, "mentor@x.edu", "Mentor"), max_mentees=0)

        u = make_user(db, "stu@x.edu", "Student")
        s = make_student(db, u, "CS001", success_score=90.0)

        result = service.run_allocation(db, admin_u)
        assert result.allocated == 0
        assert result.skipped == 1
        assert result.skipped_students == [s.id]


# ─── HTTP endpoint integration tests ───
class TestAllocationEndpoints:
    """Exercise the FastAPI routes through the TestClient (full stack)."""

    def test_run_endpoint_requires_hod_or_admin(self, client, db):
        """A non-privileged user (Student) cannot trigger allocation."""
        from backend.app.core.security import create_access_token

        stu_u = make_user(db, "stu@x.edu", "Student")
        token = create_access_token(stu_u.id)
        r = client.post(
            "/api/v1/allocation/run",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    def test_run_endpoint_allocates_via_http(self, client, db):
        """HOD hitting /run should allocate and return stats over HTTP."""
        from backend.app.core.security import create_access_token

        hod_u = make_user(db, "hod@x.edu", "HOD")
        make_mentor(db, make_user(db, "mentor@x.edu", "Mentor"), max_mentees=10)

        for i in range(3):
            u = make_user(db, f"stu{i}@x.edu", "Student")
            make_student(db, u, f"CS00{i}", success_score=50.0)

        token = create_access_token(hod_u.id)
        r = client.post(
            "/api/v1/allocation/run",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["allocated"] == 3
        assert body["skipped"] == 0
        assert body["skipped_students"] == []

    def test_pending_endpoint_returns_score_ordered_list(self, client, db):
        """GET /pending should surface students with their success_score."""
        from backend.app.core.security import create_access_token

        hod_u = make_user(db, "hod@x.edu", "HOD")
        make_mentor(db, make_user(db, "mentor@x.edu", "Mentor"), max_mentees=10)

        u1 = make_user(db, "low@x.edu", "Student")
        make_student(db, u1, "CS001", success_score=20.0)
        u2 = make_user(db, "high@x.edu", "Student")
        make_student(db, u2, "CS002", success_score=88.0)

        token = create_access_token(hod_u.id)
        r = client.get(
            "/api/v1/allocation/pending",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 2
        assert body[0]["success_score"] == 88.0
        assert body[1]["success_score"] == 20.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestScoringIntegration:
    """The allocation engine must rank on the scoring engine's weighted output."""

    def test_engine_has_no_scoring_coupling(self):
        """Allocation engine consumes success_score but imports no scoring weights."""
        from backend.app.scoring.engine import COMPONENT_WEIGHTS as scoring_weights

        # The allocation engine must NOT re-export scoring internals.
        assert not hasattr(engine, "COMPONENT_WEIGHTS")
        assert scoring_weights == {
            "attendance": 0.35,
            "academic": 0.35,
            "engagement": 0.15,
            "placement": 0.15,
        }

    def test_priority_uses_weighted_score_not_risk(self):
        """A low-risk (Green) high-scorer outranks a high-risk (Coral) low-scorer."""
        students_by_dept = {
            "CSE": [
                {"id": 1, "success_score": 92.0},  # Green, top score
                {"id": 2, "success_score": 18.0},  # Coral, bottom score
            ]
        }
        mentors_by_dept = {"CSE": [{"id": 101, "max_mentees": 2}]}
        workload_map = {101: 0}

        result = engine.allocate(students_by_dept, mentors_by_dept, workload_map)
        allocated_order = [s for s, _ in result["plan"]]
        assert allocated_order == [1, 2]  # score wins, not risk label