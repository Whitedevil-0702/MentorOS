/**
 * Shared domain types.
 *
 * These deliberately mirror the shape the eventual REST API will return, so
 * that swapping the mock layer for real `fetch` calls (in /src/api) requires
 * no changes here or in any component. See the "backend hand-off contract"
 * in the build brief, Section 4.
 */

export type RiskCategory = "green" | "amber" | "coral";

/**
 * Lowercase UI role. The backend stores/returns capitalised roles
 * ("Student" | "Mentor" | "HOD" | "Admin"); normalise at the API boundary
 * with `toRole()` in `@/api/adapters` before using them here.
 */
export type Role = "student" | "mentor" | "hod" | "admin";

/** GET /students/:id/score */
export interface ScoreBreakdown {
  attendance_component: number;
  academic_component: number;
  engagement_component: number;
  placement_component: number;
  total_score: number;
  risk_category: RiskCategory;
}

/** Raw inputs the score is derived from — what an SIS/LMS would feed us. */
export interface StudentSignals {
  /** Attendance percentage, 0–100. */
  attendance_pct: number;
  /** Per-subject internal marks. */
  subjects: SubjectMark[];
  /** Count of currently active backlogs (failed/uncleared papers). */
  active_backlogs: number;
  /** Logins in the trailing 30 days. */
  logins_30d: number;
  /** Assignment submission rate, 0–1. */
  assignment_submission_rate: number;
  /** Placement-readiness checklist. */
  placement_profile: PlacementProfile;
}

export interface SubjectMark {
  code: string;
  name: string;
  internal_marks: number;
  max_internal: number;
}

export interface PlacementProfile {
  resume_uploaded: boolean;
  skills_listed: boolean;
  certifications_added: boolean;
}

export interface Student {
  id: string;
  name: string;
  roll_no: string;
  email: string;
  department_id: string;
  mentor_id: string;
  semester: number;
  avatar_hue: number;
  signals: StudentSignals;
  score: ScoreBreakdown;
  /** Trailing semester scores for the trend line, oldest → newest. */
  score_history: ScorePoint[];
  consents: ConsentSettings;
}

export interface ScorePoint {
  label: string;
  total_score: number;
}

export interface ConsentSettings {
  academic: boolean;
  attendance: boolean;
  placement: boolean;
  /** No data source yet — rendered locked. */
  wellness: boolean;
}

export interface Mentor {
  id: string;
  name: string;
  email: string;
  department_id: string;
  title: string;
  avatar_hue: number;
}

export interface Department {
  id: string;
  name: string;
  code: string;
  hod_name: string;
}

export type MeetingStatus = "scheduled" | "completed" | "cancelled";

export interface Meeting {
  id: string;
  student_id: string;
  mentor_id: string;
  /** ISO datetime. */
  scheduled_for: string;
  status: MeetingStatus;
  mode: "in-person" | "video" | "phone";
  /** Populated once logged. */
  log?: MeetingLog;
}

export interface MeetingLog {
  topics: string[];
  summary: string;
  action_items: ActionItem[];
  next_meeting_date?: string;
  logged_at: string;
}

export interface ActionItem {
  id: string;
  text: string;
  owner: "student" | "mentor";
  done: boolean;
}

/** A row in the mentor roster — student plus mentoring context. */
export interface RosterEntry {
  student: Student;
  last_meeting?: Meeting;
  next_meeting?: Meeting;
  open_action_items: number;
}

/** Aggregates for the HOD dashboard. */
export interface DepartmentOverview {
  department: Department;
  total_students: number;
  risk_counts: Record<RiskCategory, number>;
  avg_score: number;
  mentor_loads: MentorLoad[];
  /** Risk distribution per semester for the heatmap. */
  semester_risk: SemesterRisk[];
  trend: ScorePoint[];
}

export interface MentorLoad {
  mentor: Mentor;
  mentee_count: number;
  risk_counts: Record<RiskCategory, number>;
  avg_score: number;
  meetings_this_month: number;
}

export interface SemesterRisk {
  semester: number;
  green: number;
  amber: number;
  coral: number;
}

/** Admin user-management row. */
export interface PlatformUser {
  id: string;
  name: string;
  email: string;
  role: Role;
  department_code: string;
  status: "active" | "invited" | "suspended";
  last_active: string;
}

export interface AllocationDepartmentRunStats {
  allocated: number;
  skipped: number;
}

export interface AllocationRunResponse {
  allocated: number;
  skipped: number;
  skipped_students: number[];
  by_department: Record<string, AllocationDepartmentRunStats>;
}

export interface AllocationResetResponse {
  cleared: number;
}

export interface AllocationDepartmentStatistics {
  total_students: number;
  total_mentors: number;
  allocated: number;
  pending: number;
}

export interface AllocationStatistics {
  total_students: number;
  total_mentors: number;
  allocated: number;
  pending: number;
  by_department: Record<string, AllocationDepartmentStatistics>;
}

export interface AllocationMenteeSummary {
  id: number;
  usn: string;
  full_name: string;
  risk_status: string;
}

export interface AllocationMentorWorkload {
  mentor_id: number;
  mentor_name: string;
  department: string;
  current: number;
  max: number;
  mentees: AllocationMenteeSummary[];
}

export interface AllocationPendingStudent {
  id: number;
  usn: string;
  full_name: string;
  department: string;
  risk_status: string;
  success_score: number | null;
}
