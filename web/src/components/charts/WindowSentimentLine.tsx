import {
  Area,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  EmptyTile,
  TooltipShell,
  tooltipCursor,
  xAxisDefaults,
  yAxisDefaults,
} from "./_chart-axis";
import { SENTIMENT_COLORS } from "../../lib/sentiment";
import { formatPtBr } from "../../lib/date";

export type DailyPoint = {
  date: string;
  net: number;
  total: number;
  positive: number;
  neutral: number;
  negative: number;
};

export function WindowSentimentLine({ data }: { data: DailyPoint[] }) {
  if (!data.length) return <EmptyTile />;
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={data}
          margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
        >
          <defs>
            <linearGradient id="netPos" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={SENTIMENT_COLORS.positive} stopOpacity={0.5} />
              <stop offset="100%" stopColor={SENTIMENT_COLORS.positive} stopOpacity={0} />
            </linearGradient>
            <linearGradient id="netNeg" x1="0" y1="1" x2="0" y2="0">
              <stop offset="0%" stopColor={SENTIMENT_COLORS.negative} stopOpacity={0.5} />
              <stop offset="100%" stopColor={SENTIMENT_COLORS.negative} stopOpacity={0} />
            </linearGradient>
          </defs>
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
          <YAxis
            domain={[-1, 1]}
            ticks={[-1, -0.5, 0, 0.5, 1]}
            tickFormatter={(v: number) => v.toFixed(1)}
            width={36}
            {...yAxisDefaults}
          />
          <ReferenceLine y={0} stroke="hsl(var(--border))" />
          <Tooltip cursor={tooltipCursor} content={<DailyTooltip />} />
          <Area
            type="monotone"
            dataKey={(d: DailyPoint) => Math.max(0, d.net)}
            stroke={SENTIMENT_COLORS.positive}
            strokeWidth={2}
            fill="url(#netPos)"
            isAnimationActive={false}
          />
          <Area
            type="monotone"
            dataKey={(d: DailyPoint) => Math.min(0, d.net)}
            stroke={SENTIMENT_COLORS.negative}
            strokeWidth={2}
            fill="url(#netNeg)"
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function DailyTooltip({
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
      <div className="grid grid-cols-2 gap-x-3 mt-1 tabular-nums">
        <span className="text-muted-foreground">Net</span>
        <span className="text-right">{d.net.toFixed(2)}</span>
        <span className="text-muted-foreground">Total</span>
        <span className="text-right">{d.total}</span>
      </div>
      {d.total > 0 && (
        <div className="mt-1 tabular-nums">
          <span style={{ color: SENTIMENT_COLORS.positive }}>+{d.positive}</span>
          {" / "}
          <span style={{ color: SENTIMENT_COLORS.neutral }}>={d.neutral}</span>
          {" / "}
          <span style={{ color: SENTIMENT_COLORS.negative }}>−{d.negative}</span>
        </div>
      )}
    </TooltipShell>
  );
}
