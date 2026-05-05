import {
  Bar,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
// Point is a structural shape so both /sentiment-series (selected-day) and
// /trends/company (rolling window) endpoints can feed this chart.
export type SeriesPoint = {
  date: string;
  close: number | null;
  net: number;
  total: number;
  positive: number;
  neutral: number;
  negative: number;
};
import {
  EmptyTile,
  TooltipShell,
  tooltipCursor,
  xAxisDefaults,
  yAxisDefaults,
} from "./_chart-axis";
import { SENTIMENT_COLORS } from "../../lib/sentiment";
import { formatPtBr } from "../../lib/date";

const PRICE_COLOR = "hsl(var(--primary))";

export type SentimentVsPriceChartProps = {
  data: { points: SeriesPoint[]; selectedDate?: string };
};

export function SentimentVsPriceChart({ data }: SentimentVsPriceChartProps) {
  if (!data.points.length) {
    return <EmptyTile label="— sem dados —" />;
  }

  const closes = data.points
    .map((p) => p.close)
    .filter((v): v is number => v !== null);
  const hasClose = closes.length > 0;
  const minClose = hasClose ? Math.min(...closes) : 0;
  const maxClose = hasClose ? Math.max(...closes) : 1;
  const padClose = (maxClose - minClose) * 0.05 || maxClose * 0.01 || 1;

  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={data.points}
          margin={{ top: 8, right: 56, left: 0, bottom: 0 }}
        >
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
            yAxisId="net"
            domain={[-1, 1]}
            ticks={[-1, -0.5, 0, 0.5, 1]}
            tickFormatter={(v: number) => v.toFixed(1)}
            width={36}
            {...yAxisDefaults}
          />
          <YAxis
            yAxisId="price"
            orientation="right"
            domain={[minClose - padClose, maxClose + padClose]}
            tickFormatter={(v: number) => v.toFixed(2)}
            width={48}
            {...yAxisDefaults}
          />
          <ReferenceLine yAxisId="net" y={0} stroke="hsl(var(--border))" />
          {data.selectedDate && (
            <ReferenceLine
              yAxisId="net"
              x={data.selectedDate}
              stroke="hsl(var(--primary) / 0.4)"
              strokeDasharray="3 3"
            />
          )}
          <Tooltip cursor={tooltipCursor} content={<SeriesTooltip />} />
          <Bar
            yAxisId="net"
            dataKey="net"
            name="Net sentiment"
            isAnimationActive={false}
            shape={(props: BarShapeProps) => <NetBar {...props} />}
          />
          <Line
            yAxisId="price"
            type="monotone"
            dataKey="close"
            name="Fechamento"
            stroke={PRICE_COLOR}
            strokeWidth={2}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

type BarShapeProps = {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: SeriesPoint;
};

function NetBar({ x, y, width, height, payload }: BarShapeProps) {
  if (
    x == null ||
    y == null ||
    width == null ||
    height == null ||
    !payload
  )
    return null;
  if (payload.total === 0) return null;
  const fill =
    payload.net > 0
      ? SENTIMENT_COLORS.positive
      : payload.net < 0
        ? SENTIMENT_COLORS.negative
        : SENTIMENT_COLORS.neutral;
  return <rect x={x} y={y} width={width} height={height} fill={fill} opacity={0.7} />;
}

function SeriesTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: SeriesPoint }>;
}) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <TooltipShell>
      <div className="uppercase tracking-widest text-muted-foreground/80">
        {formatPtBr(p.date)}
      </div>
      <div className="grid grid-cols-2 gap-x-3 mt-1 tabular-nums">
        <span className="text-muted-foreground">Fech.</span>
        <span className="text-right">{p.close === null ? "—" : p.close.toFixed(2)}</span>
        <span className="text-muted-foreground">Net</span>
        <span className="text-right">{p.net.toFixed(2)}</span>
        <span className="text-muted-foreground">Artigos</span>
        <span className="text-right">{p.total}</span>
      </div>
      {p.total > 0 && (
        <div className="mt-1 tabular-nums">
          <span style={{ color: SENTIMENT_COLORS.positive }}>+{p.positive}</span>
          {" / "}
          <span style={{ color: SENTIMENT_COLORS.neutral }}>={p.neutral}</span>
          {" / "}
          <span style={{ color: SENTIMENT_COLORS.negative }}>−{p.negative}</span>
        </div>
      )}
    </TooltipShell>
  );
}
