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
import { SENTIMENT_COLORS, SENTIMENT_LABEL_PT, type SentimentTone } from "../../lib/sentiment";
import {
  EmptyTile,
  SentimentBreakdown,
  TooltipShell,
  tooltipCursor,
  xAxisDefaults,
  yAxisDefaults,
} from "./_chart-axis";

const STACK: SentimentTone[] = ["positive", "neutral", "negative"];

type Datum = ReportPayload["topTickers"][number];

function TickerTooltip({
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
      <div className="uppercase tracking-widest text-muted-foreground/80">{d.ticker}</div>
      <SentimentBreakdown {...d} />
      <div className="mt-1 text-muted-foreground/80">total {d.total}</div>
    </TooltipShell>
  );
}

export function TopTickers({
  data,
}: {
  data: Pick<ReportPayload, "topTickers">;
}) {
  const rows = data.topTickers.slice(0, 15).slice().reverse();

  return (
    <ChartCard title="Top tickers" subtitle="empresas casadas">
      {rows.length === 0 ? (
        <EmptyTile />
      ) : (
        <div style={{ height: Math.max(rows.length * 24, 280) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout="vertical" margin={{ left: 0, right: 16 }}>
              <XAxis type="number" {...xAxisDefaults} />
              <YAxis
                type="category"
                dataKey="ticker"
                width={56}
                {...yAxisDefaults}
              />
              <Tooltip cursor={tooltipCursor} content={<TickerTooltip />} />
              {STACK.map((tone) => (
                <Bar
                  key={tone}
                  dataKey={tone}
                  stackId="s"
                  fill={SENTIMENT_COLORS[tone]}
                  name={SENTIMENT_LABEL_PT[tone]}
                  radius={tone === "negative" ? [0, 4, 4, 0] : undefined}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}
