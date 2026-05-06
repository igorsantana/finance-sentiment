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

type ChartPoint = SeriesPoint & { _ref: number };

const PRICE_COLOR = "hsl(var(--primary))";

export type SentimentVsPriceChartProps = {
  data: { points: SeriesPoint[]; selectedDate?: string };
};

export function SentimentVsPriceChart({ data }: SentimentVsPriceChartProps) {
  if (!data.points.length) {
    return <EmptyTile label="— sem dados —" />;
  }

  const maxCount = Math.max(
    ...data.points.map((p) => Math.max(p.positive, p.negative)),
    1,
  );
  const chartData: ChartPoint[] = data.points.map((p) => ({ ...p, _ref: maxCount }));

  const closes = data.points
    .map((p) => p.close)
    .filter((v): v is number => v !== null);
  const hasClose = closes.length > 0;
  const minClose = hasClose ? Math.min(...closes) : 0;
  const maxClose = hasClose ? Math.max(...closes) : 1;
  const padClose = (maxClose - minClose) * 0.05 || maxClose * 0.01 || 1;

  const barShape = (props: any) => {
    const { x, y, width, height, payload } = props;
    const zeroY = y + height;
    const ppu = height / maxCount;
    const posH = payload.positive * ppu;
    const negH = payload.negative * ppu;
    const bw = Math.max(width - 2, 1);
    return (
      <g>
        {posH > 0.5 && (
          <rect
            x={x + 1} y={zeroY - posH} width={bw} height={posH}
            fill={SENTIMENT_COLORS.positive} rx={2}
          />
        )}
        {negH > 0.5 && (
          <rect
            x={x + 1} y={zeroY} width={bw} height={negH}
            fill={SENTIMENT_COLORS.negative} rx={2}
          />
        )}
      </g>
    );
  };

  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={chartData}
          margin={{ top: 8, right: hasClose ? 56 : 8, left: 0, bottom: 0 }}
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
            yAxisId="count"
            domain={[-maxCount, maxCount]}
            tickFormatter={(v: number) => String(Math.abs(v))}
            width={28}
            {...yAxisDefaults}
          />
          {hasClose && (
            <YAxis
              yAxisId="price"
              orientation="right"
              domain={[minClose - padClose, maxClose + padClose]}
              tickFormatter={(v: number) => v.toFixed(2)}
              width={48}
              {...yAxisDefaults}
            />
          )}
          <ReferenceLine yAxisId="count" y={0} stroke="hsl(var(--border))" />
          {data.selectedDate && (
            <ReferenceLine
              yAxisId="count"
              x={data.selectedDate}
              stroke="hsl(var(--primary) / 0.4)"
              strokeDasharray="3 3"
            />
          )}
          <Tooltip cursor={tooltipCursor} content={<SeriesTooltip />} />
          <Bar
            yAxisId="count"
            dataKey="_ref"
            fillOpacity={0}
            isAnimationActive={false}
            shape={barShape}
          />
          {hasClose && (
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="close"
              stroke={PRICE_COLOR}
              strokeWidth={2}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function SeriesTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: ChartPoint }>;
}) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <TooltipShell>
      <div className="uppercase tracking-widest text-muted-foreground/80">
        {formatPtBr(p.date)}
      </div>
      <div className="grid grid-cols-2 gap-x-3 mt-1 tabular-nums">
        {p.close !== null && (
          <>
            <span className="text-muted-foreground">Fech.</span>
            <span className="text-right">{p.close?.toFixed(2)}</span>
          </>
        )}
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
