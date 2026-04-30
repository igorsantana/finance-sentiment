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

type Datum = ReportPayload["currencies"][number];

function CurrencyTooltip({
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
        {d.currency}
      </div>
      <div className="mt-1 tabular-nums text-foreground">{d.count} menções</div>
    </TooltipShell>
  );
}

export function Currencies({ data }: { data: ReportPayload }) {
  const rows = data.currencies.slice().reverse();

  return (
    <ChartCard title="Moedas mencionadas">
      {rows.length === 0 ? (
        <EmptyTile />
      ) : (
        <div style={{ height: Math.max(rows.length * 26, 220) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout="vertical" margin={{ left: 0, right: 16 }}>
              <XAxis type="number" {...xAxisDefaults} />
              <YAxis
                type="category"
                dataKey="currency"
                width={56}
                {...yAxisDefaults}
              />
              <Tooltip cursor={tooltipCursor} content={<CurrencyTooltip />} />
              <Bar
                dataKey="count"
                fill="hsl(var(--sentiment-positive))"
                radius={[0, 4, 4, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}
