"""
Student → mentor allocation engine (score-prioritised, workload-balanced).

The engine ONLY consumes the ``success_score`` already produced by the
Scoring Engine. It never calculates, modifies, or interprets that score —
it treats it as an opaque number used purely to rank students.

Algorithm (per department):
  1. Sort students by success_score, highest first.
  2. Build a min-heap of mentors ordered by current workload.
  3. For each student: pop the least-loaded mentor, assign the student,
     increase that mentor's workload, and push the mentor back if it
     still has capacity. Students with no available mentor are skipped.

One sort + one heap per department. No database, no ORM, no scoring.
"""
from __future__ import annotations

import heapq
from typing import Any


def _sort_key(student: dict[str, Any]) -> tuple[float, int]:
    """Rank students highest-score first; ties broken by id; unscored → 0.

    This is the ONLY sort rule in the module. repository.load_unallocated
    applies the same rule when building the "pending" view, so the two
    never disagree.
    """
    score = student.get("success_score") or 0
    return (-float(score), student["id"])


def allocate(
    students_by_dept: dict[str, list[dict[str, Any]]],
    mentors_by_dept: dict[str, list[dict[str, Any]]],
    workload_map: dict[int, int],
) -> dict[str, Any]:
    """Balanced, score-prioritised allocation across all departments.

    Args:
        students_by_dept: Unallocated students grouped by department. Each
            student dict must contain ``id`` and ``success_score`` (0–100).
        mentors_by_dept: Mentors grouped by department. Each mentor dict must
            contain ``id`` and ``max_mentees``.
        workload_map: Current mentee counts keyed by mentor id.

    Returns:
        Dict with ``plan`` — a list of ``(student_id, mentor_id)`` pairs — and
        ``stats`` with ``allocated``, ``skipped``, ``skipped_students`` (the ids
        that could not be placed) and a per-department breakdown.
    """
    plan: list[tuple[int, int]] = []
    total_allocated = 0
    total_skipped = 0
    skipped_students: list[int] = []
    by_dept: dict[str, dict[str, int]] = {}
    running_workload = dict(workload_map)

    for dept, students in students_by_dept.items():
        dept_allocated = 0
        dept_skipped = 0
        dept_skipped_ids: list[int] = []
        mentors = mentors_by_dept.get(dept, [])

        # Min-heap of mentors ordered by (current_load, mentor_id, max_mentees).
        # mentor_id is unique, so it alone breaks ties — no extra counter needed.
        # Popping returns the mentor carrying the lightest current load.
        heap: list[tuple[int, int, int]] = []
        for mentor in mentors:
            mentor_id = mentor["id"]
            current = running_workload.get(mentor_id, 0)
            if current < mentor["max_mentees"]:
                heapq.heappush(heap, (current, mentor_id, mentor["max_mentees"]))

        # Highest success_score first → first pick of the lightest mentor.
        for student in sorted(students, key=_sort_key):
            if not heap:
                dept_skipped += 1
                dept_skipped_ids.append(student["id"])
                continue

            load, mentor_id, max_mentees = heapq.heappop(heap)
            plan.append((student["id"], mentor_id))
            dept_allocated += 1

            new_load = load + 1
            running_workload[mentor_id] = new_load
            if new_load < max_mentees:
                heapq.heappush(heap, (new_load, mentor_id, max_mentees))

        by_dept[dept] = {"allocated": dept_allocated, "skipped": dept_skipped}
        total_allocated += dept_allocated
        total_skipped += dept_skipped
        skipped_students.extend(dept_skipped_ids)

    return {
        "plan": plan,
        "stats": {
            "allocated": total_allocated,
            "skipped": total_skipped,
            "skipped_students": skipped_students,
            "by_dept": by_dept,
        },
    }
