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

type Datum = ReportPayload["hourly"][number];

function HourlyTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: Datum }>;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const total = d.positive + d.neutral + d.negative;
  return (
    <TooltipShell>
      <div className="uppercase tracking-widest text-muted-foreground/80">
        {String(d.hour).padStart(2, "0")}:00
      </div>
      <SentimentBreakdown {...d} />
      <div className="mt-1 text-muted-foreground/80">total {total}</div>
    </TooltipShell>
  );
}

export function HourlyTimeline({ data }: { data: ReportPayload }) {
  const rows = data.hourly;
  const total = rows.reduce(
    (acc, h) => acc + h.positive + h.neutral + h.negative,
    0,
  );

  return (
    <ChartCard title="Linha do tempo (hora)" subtitle="0–23h America/Sao_Paulo">
      {total === 0 ? (
        <EmptyTile />
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <XAxis
                dataKey="hour"
                ticks={[0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22]}
                tickFormatter={(h: number) => String(h).padStart(2, "0")}
                {...xAxisDefaults}
              />
              <YAxis width={28} {...yAxisDefaults} />
              <Tooltip cursor={tooltipCursor} content={<HourlyTooltip />} />
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
