"""
Student → mentor allocation engine (score-prioritised, workload-balanced).

Consumes only the ``success_score`` already produced by the Scoring Engine.
It never calculates, modifies, or interprets that score — it treats it as an
opaque number used purely to rank students.

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


def _build_mentor_heap(
    mentors_by_dept: dict[str, dict[int, int]],
    running_workload: dict[int, int],
) -> dict[str, list[tuple[int, int]]]:
    """Build a min-heap of (load, mentor_id) for each department.

    Mentors already at capacity are excluded from the heap.
    """
    mentor_heaps: dict[str, list[tuple[int, int]]] = {}
    for dept, max_mentees in mentors_by_dept.items():
        heap: list[tuple[int, int]] = []
        for mentor_id, max_m in max_mentees.items():
            current_load = running_workload.get(mentor_id, 0)
            if current_load < max_m:
                heapq.heappush(heap, (current_load, mentor_id))
        mentor_heaps[dept] = heap
    return mentor_heaps


def _assign_student(
    student_id: int,
    mentor_id: int,
    plan: list[tuple[int, int]],
    load: int,
    max_mentees: int,
    running_workload: dict[int, int],
    mentor_heap: list[tuple[int, int]],
) -> None:
    """Assign a student to a mentor and update the heap if capacity remains."""
    plan.append((student_id, mentor_id))
    new_load = load + 1
    running_workload[mentor_id] = new_load
    if new_load < max_mentees:
        heapq.heappush(mentor_heap, (new_load, mentor_id))


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
    if not students_by_dept or not mentors_by_dept:
        return {"plan": [], "stats": {"allocated": 0, "skipped": 0, "skipped_students": [], "by_dept": {}}}

    plan: list[tuple[int, int]] = []
    total_allocated = 0
    total_skipped = 0
    skipped_student_ids: list[int] = []
    department_stats: dict[str, dict[str, int]] = {}
    running_workload = dict(workload_map)

    # Build max_mentees lookup once per department
    max_mentees_by_dept: dict[str, dict[int, int]] = {
        dept: {mentor["id"]: mentor["max_mentees"] for mentor in mentors}
        for dept, mentors in mentors_by_dept.items()
    }

    mentor_heaps = _build_mentor_heap(max_mentees_by_dept, running_workload)

    for dept, students in students_by_dept.items():
        allocated_count = 0
        skipped_count = 0
        skipped_ids: list[int] = []
        max_mentees = max_mentees_by_dept.get(dept, {})
        mentor_heap = mentor_heaps.get(dept, [])

        # Highest success_score first → first pick of the lightest mentor.
        for student in sorted(
            students, key=lambda s: (-(s.get("success_score") or 0), s["id"])
        ):
            if not mentor_heap:
                skipped_count += 1
                skipped_ids.append(student["id"])
                continue

            load, mentor_id = heapq.heappop(mentor_heap)
            _assign_student(
                student_id=student["id"],
                mentor_id=mentor_id,
                plan=plan,
                load=load,
                max_mentees=max_mentees[mentor_id],
                running_workload=running_workload,
                mentor_heap=mentor_heap,
            )
            allocated_count += 1

        department_stats[dept] = {"allocated": allocated_count, "skipped": skipped_count}
        total_allocated += allocated_count
        total_skipped += skipped_count
        skipped_student_ids.extend(skipped_ids)

    return {
        "plan": plan,
        "stats": {
            "allocated": total_allocated,
            "skipped": total_skipped,
            "skipped_students": skipped_student_ids,
            "by_dept": department_stats,
        },
    }