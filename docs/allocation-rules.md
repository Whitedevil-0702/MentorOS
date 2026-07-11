# Student-Mentor Allocation Rules — MentorOS

This document specifies the exact matching, balancing, and priority rules governing how students are allocated to faculty mentors. These rules must be enforced programmatically by the allocation routers.

---

## 1. Rule: Department Alignment
- **Requirement**: A student **must** only be allocated to a mentor belonging to the same academic department.
- **Verification**: `student.department == mentor.department`
- **Exceptions**: None. Inter-departmental mentoring is disallowed to ensure domain-specific academic guidance.

---

## 2. Rule: Roster Capacity Limits
- **Requirement**: A mentor cannot exceed their maximum allowed mentee capacity.
- **Verification**:
  $$\text{Count}(\text{student} \in \text{mentor.students}) < \text{mentor.max\_mentees}$$
- **Default capacity**: 20 students per mentor.
- **Override**: Admins can adjust `mentor.max_mentees` individually (e.g. senior HODs might have a lower cap like 10, whereas full-time mentors might take up to 30).
- **Enforcement**: If a manual or automatic allocation request would push a mentor beyond their capacity cap, the API must return `HTTP 400 Bad Request`.

---

## 3. Rule: Auto-Allocation and Balancing
When triggering automatic cohort allocation, the system distributes unassigned students using a balanced-load algorithm:
1. **Scope Identification**: Filter all unassigned students in department $D$ and all active mentors in department $D$.
2. **Sort Mentors**: Order mentors in department $D$ in ascending order of their current assigned mentee count.
3. **Assign and Cycle**:
   - Assign the next unassigned student to the mentor with the lowest count.
   - Increment that mentor's count.
   - Re-sort or round-robin to ensure load remains balanced within $\pm 1$ student difference.
4. **Capacity Block**: If all mentors reach their `max_mentees` limit, the auto-allocation job halts and logs a warning requesting admin capacity updates.

---

## 4. Rule: Prioritization by Success Score
Allocation priority is driven by each student's **Student Success Score** — the
weighted blend `0.35·Attendance + 0.35·Academic + 0.15·Engagement + 0.15·Placement`
computed by the scoring engine (`backend/app/scoring/engine.py`,
`COMPONENT_WEIGHTS`). The weights live in one place and are shared with the
allocation engine so scoring and allocation never drift apart.

- Students are ranked **highest success_score first**; ties are broken by
  ascending `student.id` for deterministic output. Unscored students
  (`success_score` is `NULL`) are treated as `0` and sink to the bottom of the queue.
- The highest-scoring student in a department is assigned first and gets first
  pick of the **mentor carrying the lightest current load**, so strong students
  are paired with mentors who have the most capacity to engage them.
- Within a department, a per-mentor min-heap keeps loads balanced to **±1
  mentee** — no mentor is overloaded while a colleague sits idle.
- If a department's mentors are all at `max_mentees`, the remaining students are
  **not silently dropped**: the run response returns `skipped_students` (their
  ids) and an audit entry is written so the HOD can raise capacity or add mentors.
