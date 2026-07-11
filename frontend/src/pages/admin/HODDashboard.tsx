import { AlertTriangle, GraduationCap, TrendingUp, Users2 } from "lucide-react";
import { getDepartmentOverview } from "@/api";
import { RISK_META, RISK_ORDER } from "@/lib/score";
import { useAsync } from "@/lib/useAsync";
import { Button, EmptyState, GlassCard, LoadingState } from "@/components/primitives";
import { SectionHeading } from "@/components/SectionHeading";
import { StatTile } from "@/components/StatTile";
import { AllocationManager } from "@/components/allocation/AllocationManager";
import { RiskHeatmap } from "@/features/hod/RiskHeatmap";
import { MentorWorkloadChart } from "@/features/hod/MentorWorkloadChart";
import { SemesterTrendChart } from "@/features/hod/SemesterTrendChart";

export default function HODDashboard() {
  const overview = useAsync(() => getDepartmentOverview(), []);

  if (overview.loading) return <LoadingState label="Loading department overview…" />;
  if (overview.error || !overview.data) {
    return (
      <EmptyState
        icon={<AlertTriangle size={22} />}
        title="We couldn't load the department overview"
        body={overview.error ?? "Something went wrong."}
        action={<Button onClick={overview.reload}>Try again</Button>}
      />
    );
  }

  const d = overview.data;
  const total = d.total_students;

  return (
    <div className="flex flex-col gap-8">
      <SectionHeading
        id="overview"
        title={d.department.name}
        description={`${total} students · ${d.mentor_loads.length} mentors · led by ${d.department.hod_name}`}
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Students" value={total} icon={<GraduationCap size={18} />} sublabel="Across all semesters" />
        <StatTile
          label="Avg Success Score"
          value={d.avg_score}
          icon={<TrendingUp size={18} />}
          sublabel="Department-wide"
        />
        <StatTile
          label="At risk"
          value={d.risk_counts.coral}
          accent={RISK_META.coral.hex}
          sublabel={`${Math.round((d.risk_counts.coral / total) * 100)}% of cohort`}
        />
        <StatTile label="Mentors" value={d.mentor_loads.length} icon={<Users2 size={18} />} sublabel="Active this term" />
      </div>

      {/* Overall risk proportion */}
      <GlassCard className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="font-display text-body font-semibold text-ink">Risk distribution</h3>
          <span className="font-mono tnum text-caption text-ink-soft">{total} students</span>
        </div>
        <div className="flex h-4 w-full overflow-hidden rounded-full">
          {RISK_ORDER.map((cat) => {
            const count = d.risk_counts[cat];
            const pct = (count / total) * 100;
            return (
              <div
                key={cat}
                style={{ width: `${pct}%`, background: RISK_META[cat].hex }}
                title={`${RISK_META[cat].label}: ${count}`}
              />
            );
          })}
        </div>
        <div className="flex flex-wrap gap-4">
          {RISK_ORDER.map((cat) => (
            <div key={cat} className="flex items-center gap-2 text-caption">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: RISK_META[cat].hex }} />
              <span className="text-ink-soft">{RISK_META[cat].label}</span>
              <span className="font-mono tnum font-semibold text-ink">{d.risk_counts[cat]}</span>
            </div>
          ))}
        </div>
      </GlassCard>

      <AllocationManager />

      <div className="grid gap-5 lg:grid-cols-2">
        {/* Heatmap */}
        <section className="flex flex-col gap-3">
          <SectionHeading
            id="heatmap"
            title="Risk heatmap"
            description="Where risk concentrates by semester."
          />
          <GlassCard>
            <RiskHeatmap data={d.semester_risk} />
          </GlassCard>
        </section>

        {/* Trend */}
        <section className="flex flex-col gap-3">
          <SectionHeading
            id="trend"
            title="Semester trend"
            description="Average score over the last five terms."
          />
          <GlassCard>
            <SemesterTrendChart trend={d.trend} />
          </GlassCard>
        </section>
      </div>

      {/* Workload */}
      <section className="flex flex-col gap-3">
        <SectionHeading
          id="workload"
          title="Mentor workload"
          description="Mentee count and risk mix per mentor — to balance the load."
        />
        <GlassCard>
          <MentorWorkloadChart loads={d.mentor_loads} />
        </GlassCard>
      </section>
    </div>
  );
}
