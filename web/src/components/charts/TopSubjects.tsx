import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ReportPayload } from "../../api";
import { ChartCard } from "./ChartCard";
import {
  EmptyTile,
  TooltipShell,
  tooltipCursor,
  xAxisDefaults,
  yAxisDefaults,
} from "./_chart-axis";

type Datum = ReportPayload["topSubjects"][number];

function SubjectTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: Datum }>;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <TooltipShell>
      <div className="uppercase tracking-widest text-muted-foreground/80">
        {d.subject}
      </div>
      <div className="mt-1 tabular-nums text-foreground">{d.count} artigos</div>
    </TooltipShell>
  );
}

export function TopSubjects({ data }: { data: ReportPayload }) {
  const rows = data.topSubjects.slice(0, 15).slice().reverse();

  return (
    <ChartCard title="Top assuntos" subtitle="por contagem">
      {rows.length === 0 ? (
        <EmptyTile />
      ) : (
        <div style={{ height: Math.max(rows.length * 22, 280) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 16 }}>
              <XAxis type="number" {...xAxisDefaults} />
              <YAxis
                type="category"
                dataKey="subject"
                width={140}
                {...yAxisDefaults}
              />
              <Tooltip cursor={tooltipCursor} content={<SubjectTooltip />} />
              <Bar
                dataKey="count"
                fill="hsl(var(--primary))"
                radius={[0, 4, 4, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}
