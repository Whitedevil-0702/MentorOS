import type {
  AllocationMentorWorkload,
  AllocationPendingStudent,
  AllocationResetResponse,
  AllocationRunResponse,
  AllocationStatistics,
} from "@/types";

const BASE = "/api/v1/allocation";

function allocationHeaders(): HeadersInit {
  const token = sessionStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function readJson<T>(res: Response): Promise<T> {
  if (res.ok) return res.json() as Promise<T>;

  let detail = "";
  try {
    const body = (await res.json()) as { detail?: unknown };
    detail = typeof body.detail === "string" ? body.detail : "";
  } catch {
    detail = "";
  }

  if (res.status === 401 || res.status === 403) {
    throw new Error(detail || "Allocation API requires an HOD or Admin session.");
  }

  throw new Error(detail || `Allocation API request failed (HTTP ${res.status}).`);
}

function request<T>(path: string, init?: RequestInit): Promise<T> {
  return fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...allocationHeaders(),
      ...init?.headers,
    },
  }).then(readJson<T>);
}

export function getAllocationStatistics(): Promise<AllocationStatistics> {
  return request<AllocationStatistics>("/statistics");
}

export function getAllocationWorkload(): Promise<AllocationMentorWorkload[]> {
  return request<AllocationMentorWorkload[]>("/workload");
}

export function getAllocationPending(): Promise<AllocationPendingStudent[]> {
  return request<AllocationPendingStudent[]>("/pending");
}

export function runAllocation(): Promise<AllocationRunResponse> {
  return request<AllocationRunResponse>("/run", { method: "POST" });
}

export function resetAllocation(): Promise<AllocationResetResponse> {
  return request<AllocationResetResponse>("/reset", { method: "POST" });
}
