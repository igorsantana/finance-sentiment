import {
  Bar,
  BarChart,
  ReferenceLine,
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
import { SENTIMENT_COLORS } from "../../lib/sentiment";
import { formatPtBr } from "../../lib/date";
import type { DailyPoint } from "./WindowSentimentLine";

type ChartPoint = DailyPoint & { _ref: number };

export function WindowVolumeBars({ data }: { data: DailyPoint[] }) {
  const total = data.reduce((acc, d) => acc + d.total, 0);
  if (total === 0) return <EmptyTile />;

  const maxVal = Math.max(...data.map((d) => Math.max(d.positive, d.negative)), 1);
  const chartData: ChartPoint[] = data.map((d) => ({ ...d, _ref: maxVal }));

  // Single bar per category (full width) renders both halves via custom shape.
  // _ref = maxVal ensures height covers exactly half the chart → zeroY = y + height.
  const barShape = (props: any) => {
    const { x, y, width, height, payload } = props;
    const zeroY = y + height;
    const ppu = height / maxVal;
    const posH = payload.positive * ppu;
    const negH = payload.negative * ppu;
    const bw = Math.max(width - 2, 1);
    return (
      <g>
        {posH > 0.5 && (
          <rect x={x + 1} y={zeroY - posH} width={bw} height={posH}
            fill={SENTIMENT_COLORS.positive} rx={2} />
        )}
        {negH > 0.5 && (
          <rect x={x + 1} y={zeroY} width={bw} height={negH}
            fill={SENTIMENT_COLORS.negative} rx={2} />
        )}
      </g>
    );
  };

  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
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
            domain={[-maxVal, maxVal]}
            tickFormatter={(v: number) => String(Math.abs(v))}
            width={28}
            {...yAxisDefaults}
          />
          <ReferenceLine y={0} stroke="hsl(var(--border))" strokeWidth={1} />
          <Tooltip cursor={tooltipCursor} content={<VolumeTooltip />} />
          <Bar
            dataKey="_ref"
            fillOpacity={0}
            isAnimationActive={false}
            shape={barShape}
          />
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
  payload?: Array<{ payload: ChartPoint }>;
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
