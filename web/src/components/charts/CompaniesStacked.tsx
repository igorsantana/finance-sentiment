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
  SENTIMENT_COLORS,
  SENTIMENT_LABEL_PT,
  type SentimentTone,
} from "../../lib/sentiment";
import {
  EmptyTile,
  SentimentBreakdown,
  TooltipShell,
  tooltipCursor,
  xAxisDefaults,
  yAxisDefaults,
} from "./_chart-axis";

const STACK: SentimentTone[] = ["positive", "neutral", "negative"];

type Datum = ReportPayload["topCompanies"][number];

function StackTooltip({
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
        {d.ticker} · {d.name}
      </div>
      <SentimentBreakdown {...d} />
      <div className="mt-1 text-muted-foreground/80">
        total {d.total} · saldo {(d.tilt * 100).toFixed(0)}%
      </div>
    </TooltipShell>
  );
}

export function CompaniesStacked({ data }: { data: ReportPayload }) {
  const rows = data.topCompanies
    .slice(0, 20)
    .slice()
    .sort((a, b) => b.tilt - a.tilt)
    .reverse();

  return (
    <ChartCard
      title="Empresas — empilhado (20)"
      subtitle="ordenado por saldo"
    >
      {rows.length === 0 ? (
        <EmptyTile />
      ) : (
        <div style={{ height: Math.max(rows.length * 24, 320) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout="vertical" margin={{ left: 0, right: 16 }}>
              <XAxis type="number" {...xAxisDefaults} />
              <YAxis type="category" dataKey="ticker" width={72} {...yAxisDefaults} />
              <Tooltip cursor={tooltipCursor} content={<StackTooltip />} />
              {STACK.map((tone) => (
                <Bar
                  key={tone}
                  dataKey={tone}
                  stackId="s"
                  fill={SENTIMENT_COLORS[tone]}
                  name={SENTIMENT_LABEL_PT[tone]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}
