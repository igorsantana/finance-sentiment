import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ReportPayload } from "../../api";
import { ChartCard } from "./ChartCard";
import { SENTIMENT_COLORS, netTone } from "../../lib/sentiment";
import {
  EmptyTile,
  SentimentBreakdown,
  TooltipShell,
  tooltipCursor,
  xAxisDefaults,
  yAxisDefaults,
} from "./_chart-axis";

type Datum = ReportPayload["topCompanies"][number];

function CompanyTooltip({
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
        {d.name}
      </div>
      <SentimentBreakdown {...d} />
      <div className="mt-1 text-muted-foreground/80">
        total {d.total} · saldo {(d.tilt * 100).toFixed(0)}%
      </div>
    </TooltipShell>
  );
}

export function TopCompaniesBar({ data }: { data: ReportPayload }) {
  const rows = data.topCompanies.slice(0, 12).slice().reverse();

  return (
    <ChartCard title="Top empresas (12)" subtitle="por menções">
      {rows.length === 0 ? (
        <EmptyTile />
      ) : (
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 16 }}>
              <XAxis type="number" {...xAxisDefaults} />
              <YAxis type="category" dataKey="name" width={110} {...yAxisDefaults} />
              <Tooltip cursor={tooltipCursor} content={<CompanyTooltip />} />
              <Bar dataKey="total" radius={[0, 4, 4, 0]}>
                {rows.map((r) => (
                  <Cell
                    key={r.name}
                    fill={SENTIMENT_COLORS[netTone(r.positive, r.negative)]}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}
