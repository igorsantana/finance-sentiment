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

type Datum = ReportPayload["scoreHistogram"][number];

function HistogramTooltip({
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
      <div className="uppercase tracking-widest text-muted-foreground/80 tabular-nums">
        {d.bucketStart.toFixed(1)} – {d.bucketEnd.toFixed(1)}
      </div>
      <div className="mt-1 tabular-nums text-foreground">
        {d.count} artigos
      </div>
    </TooltipShell>
  );
}

export function ScoreHistogram({ data }: { data: ReportPayload }) {
  const rows = data.scoreHistogram;
  const total = rows.reduce((acc, r) => acc + r.count, 0);

  return (
    <ChartCard title="Histograma de score" subtitle="confiança 0–1">
      {total === 0 ? (
        <EmptyTile />
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <XAxis
                dataKey="bucketStart"
                tickFormatter={(v: number) => v.toFixed(1)}
                {...xAxisDefaults}
              />
              <YAxis width={28} {...yAxisDefaults} />
              <Tooltip cursor={tooltipCursor} content={<HistogramTooltip />} />
              <Bar dataKey="count" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}
