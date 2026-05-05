import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  EmptyTile,
  SentimentBreakdown,
  TooltipShell,
  tooltipCursor,
  xAxisDefaults,
  yAxisDefaults,
} from "./_chart-axis";
import {
  SENTIMENT_COLORS,
  SENTIMENT_LABEL_PT,
  type SentimentTone,
} from "../../lib/sentiment";
import { formatPtBr } from "../../lib/date";
import type { DailyPoint } from "./WindowSentimentLine";

const STACK: SentimentTone[] = ["positive", "neutral", "negative"];

export function WindowVolumeBars({ data }: { data: DailyPoint[] }) {
  const total = data.reduce((acc, d) => acc + d.total, 0);
  if (total === 0) return <EmptyTile />;
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <XAxis
            dataKey="date"
            tickFormatter={(iso: string) => {
              const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
              return m ? `${m[3]}/${m[2]}` : iso;
            }}
            interval="preserveStartEnd"
            minTickGap={16}
            {...xAxisDefaults}
          />
          <YAxis width={28} {...yAxisDefaults} />
          <Tooltip cursor={tooltipCursor} content={<VolumeTooltip />} />
          {STACK.map((tone) => (
            <Bar
              key={tone}
              dataKey={tone}
              stackId="s"
              fill={SENTIMENT_COLORS[tone]}
              name={SENTIMENT_LABEL_PT[tone]}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function VolumeTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: DailyPoint }>;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <TooltipShell>
      <div className="uppercase tracking-widest text-muted-foreground/80">
        {formatPtBr(d.date)}
      </div>
      <SentimentBreakdown
        positive={d.positive}
        neutral={d.neutral}
        negative={d.negative}
      />
      <div className="mt-1 text-muted-foreground/80">total {d.total}</div>
    </TooltipShell>
  );
}
