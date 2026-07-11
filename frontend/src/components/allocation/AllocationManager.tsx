import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  GitBranch,
  RotateCcw,
  UserCheck,
  UserX,
  Users2,
} from "lucide-react";
import {
  getAllocationPending,
  getAllocationStatistics,
  getAllocationWorkload,
  resetAllocation,
  runAllocation,
} from "@/api";
import type {
  AllocationMentorWorkload,
  AllocationPendingStudent,
  AllocationRunResponse,
  AllocationStatistics,
} from "@/types";
import { Button, EmptyState, GlassCard, LoadingState, Badge } from "@/components/primitives";
import { StatTile } from "@/components/StatTile";
import { toast } from "@/store/useToast";
import { cn } from "@/lib/utils";

interface AllocationData {
  statistics: AllocationStatistics;
  workload: AllocationMentorWorkload[];
  pending: AllocationPendingStudent[];
}

type ActionState = "run" | "reset" | null;

function formatNumber(value: number | null | undefined): string {
  return value == null ? "N/A" : String(Math.round(value));
}

function riskTone(risk: string): "green" | "amber" | "coral" | "neutral" {
  const normalized = risk.toLowerCase();
  if (normalized === "green") return "green";
  if (normalized === "amber") return "amber";
  if (normalized === "coral") return "coral";
  return "neutral";
}

function compactRiskLabel(risk: string): string {
  return risk || "Unknown";
}

export function AllocationManager() {
  const [data, setData] = useState<AllocationData>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [action, setAction] = useState<ActionState>(null);
  const [lastRun, setLastRun] = useState<AllocationRunResponse>();
  const [lastResetCleared, setLastResetCleared] = useState<number>();
  const [showAllWorkload, setShowAllWorkload] = useState(false);
  const [showAllPending, setShowAllPending] = useState(false);

  const refresh = useCallback(async () => {
    setError(undefined);
    const [statistics, workload, pending] = await Promise.all([
      getAllocationStatistics(),
      getAllocationWorkload(),
      getAllocationPending(),
    ]);
    setData({ statistics, workload, pending });
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    refresh()
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : "Allocation data could not be loaded.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [refresh]);

  async function handleRun() {
    setAction("run");
    setError(undefined);
    try {
      const result = await runAllocation();
      setLastRun(result);
      setLastResetCleared(undefined);
      await refresh();
      toast.success(`Allocation complete: ${result.allocated} allocated, ${result.skipped} skipped.`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Allocation run failed.";
      setError(message);
      toast.error(message);
    } finally {
      setAction(null);
    }
  }

  async function handleReset() {
    setAction("reset");
    setError(undefined);
    try {
      const result = await resetAllocation();
      setLastResetCleared(result.cleared);
      setLastRun(undefined);
      await refresh();
      toast.success(`Allocation reset cleared ${result.cleared} records.`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Allocation reset failed.";
      setError(message);
      toast.error(message);
    } finally {
      setAction(null);
    }
  }

  const visibleWorkload = showAllWorkload ? data?.workload : data?.workload.slice(0, 5);
  const visiblePending = showAllPending ? data?.pending : data?.pending.slice(0, 5);

  return (
    <GlassCard className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-md bg-azure-200/60 text-azure-600">
              <GitBranch size={18} />
            </span>
            <h2 className="font-display text-heading font-semibold text-ink">Allocation Manager</h2>
          </div>
          <p className="mt-2 text-caption text-ink-soft">
            Run the backend allocation engine and monitor mentor capacity from one place.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={handleRun}
            disabled={loading || action !== null}
            iconLeft={<UserCheck size={16} />}
          >
            {action === "run" ? "Running..." : "Run Allocation"}
          </Button>
          <Button
            variant="danger"
            onClick={handleReset}
            disabled={loading || action !== null}
            iconLeft={<RotateCcw size={16} />}
          >
            {action === "reset" ? "Resetting..." : "Reset Allocation"}
          </Button>
        </div>
      </div>

      {loading ? (
        <LoadingState label="Loading allocation manager..." />
      ) : error && !data ? (
        <EmptyState
          icon={<AlertTriangle size={22} />}
          title="Allocation data unavailable"
          body={error}
          action={<Button onClick={() => void refresh()}>Try again</Button>}
        />
      ) : data ? (
        <>
          {error && (
            <div className="rounded-md border border-signal-amber/25 bg-signal-amber/10 px-4 py-3 text-caption text-signal-amber">
              {error}
            </div>
          )}

          <section className="rounded-md border border-ink/8 bg-white/45 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-display text-body font-semibold text-ink">Allocation Engine</h3>
                <p className="mt-1 text-caption text-ink-soft">
                  Run the backend allocator and track the pending queue.
                </p>
              </div>
              <Badge tone={error ? "amber" : "green"} dot>
                {error ? "Action failed" : action ? "Working" : "Ready"}
              </Badge>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <MiniMetric label="Status" value={action ? "Working" : "Idle"} />
              <MiniMetric label="Pending students" value={data.statistics.pending} />
            </div>
            {(lastRun || lastResetCleared != null) && (
              <p className="mt-3 text-caption text-ink-soft">
                Last action:{" "}
                <span className="font-mono tnum text-ink">
                  {lastRun
                    ? `${lastRun.allocated} allocated, ${lastRun.skipped} skipped`
                    : `${lastResetCleared} cleared`}
                </span>
              </p>
            )}
          </section>

          <section>
            <div className="mb-3 flex items-center justify-between">
              <h3 className="font-display text-body font-semibold text-ink">Allocation Statistics</h3>
            </div>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile
                label="Allocated"
                value={data.statistics.allocated}
                icon={<UserCheck size={18} />}
                sublabel="Students assigned"
              />
              <StatTile
                label="Pending"
                value={data.statistics.pending}
                icon={<UserX size={18} />}
                sublabel="Awaiting mentor"
              />
              <StatTile
                label="Skipped"
                value={lastRun?.skipped ?? "-"}
                sublabel={lastRun ? "From last run" : "Run allocation to update"}
              />
              <StatTile
                label="Mentors Used"
                value={data.statistics.total_mentors}
                icon={<Users2 size={18} />}
                sublabel="Backend total"
              />
            </div>
          </section>

          <CompactTable
            title="Mentor Workload"
            count={data.workload.length}
            showingAll={showAllWorkload}
            onViewAll={() => setShowAllWorkload(true)}
            hasMore={data.workload.length > 5 && !showAllWorkload}
            emptyTitle="No mentor workload yet"
            emptyBody="Run allocation once mentors and students are available."
          >
            <thead>
              <tr className="border-b border-ink/8 text-left text-caption font-semibold uppercase tracking-wide text-ink-soft">
                <th className="px-3 py-2">Mentor</th>
                <th className="px-3 py-2">Department</th>
                <th className="px-3 py-2 text-right">Current Load</th>
                <th className="px-3 py-2 text-right">Maximum Capacity</th>
              </tr>
            </thead>
            <tbody>
              {(visibleWorkload ?? []).map((mentor) => (
                <tr key={mentor.mentor_id} className="border-b border-ink/8 last:border-0">
                  <td className="px-3 py-2.5 text-body font-medium text-ink">{mentor.mentor_name}</td>
                  <td className="px-3 py-2.5 text-caption text-ink-soft">{mentor.department}</td>
                  <td className="px-3 py-2.5 text-right font-mono tnum text-body text-ink">{mentor.current}</td>
                  <td className="px-3 py-2.5 text-right font-mono tnum text-body text-ink">{mentor.max}</td>
                </tr>
              ))}
            </tbody>
          </CompactTable>

          <CompactTable
            title="Pending Students"
            count={data.pending.length}
            showingAll={showAllPending}
            onViewAll={() => setShowAllPending(true)}
            hasMore={data.pending.length > 5 && !showAllPending}
            emptyTitle="No pending students"
            emptyBody="Every eligible student is allocated or there is no pending allocation queue."
          >
            <thead>
              <tr className="border-b border-ink/8 text-left text-caption font-semibold uppercase tracking-wide text-ink-soft">
                <th className="px-3 py-2">Student</th>
                <th className="px-3 py-2 text-right">Success Score</th>
                <th className="px-3 py-2">Department</th>
                <th className="px-3 py-2">Risk Status</th>
              </tr>
            </thead>
            <tbody>
              {(visiblePending ?? []).map((student) => (
                <tr key={student.id} className="border-b border-ink/8 last:border-0">
                  <td className="px-3 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate text-body font-medium text-ink">{student.full_name}</p>
                      <p className="font-mono tnum text-[11px] text-ink-soft">{student.usn}</p>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono tnum text-body text-ink">
                    {formatNumber(student.success_score)}
                  </td>
                  <td className="px-3 py-2.5 text-caption text-ink-soft">{student.department}</td>
                  <td className="px-3 py-2.5">
                    <Badge tone={riskTone(student.risk_status)} dot>
                      {compactRiskLabel(student.risk_status)}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </CompactTable>
        </>
      ) : null}
    </GlassCard>
  );
}

function MiniMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md bg-white/65 px-3 py-2">
      <p className="text-caption text-ink-soft">{label}</p>
      <p className="mt-1 font-mono tnum text-body font-semibold text-ink">{value}</p>
    </div>
  );
}

function CompactTable({
  title,
  count,
  children,
  hasMore,
  showingAll,
  onViewAll,
  emptyTitle,
  emptyBody,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
  hasMore: boolean;
  showingAll: boolean;
  onViewAll: () => void;
  emptyTitle: string;
  emptyBody: string;
}) {
  return (
    <section className="rounded-md border border-ink/8 bg-white/45">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink/8 px-4 py-3">
        <div>
          <h3 className="font-display text-body font-semibold text-ink">{title}</h3>
          <p className="text-caption text-ink-soft">
            {showingAll ? `Showing all ${count}` : `Showing ${Math.min(count, 5)} of ${count}`}
          </p>
        </div>
        {hasMore && (
          <Button size="sm" variant="ghost" onClick={onViewAll}>
            View All
          </Button>
        )}
      </div>
      {count === 0 ? (
        <EmptyState title={emptyTitle} body={emptyBody} className="py-8" />
      ) : (
        <div className={cn("overflow-x-auto", showingAll && "max-h-80 overflow-y-auto")}>
          <table className="w-full min-w-[560px] border-collapse">{children}</table>
        </div>
      )}
    </section>
  );
}
