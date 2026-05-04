import {
  Bar as RechartsBar,
  ComposedChart,
  Customized,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { StockOhlc } from "../../api";
import {
  EmptyTile,
  TooltipShell,
  tooltipCursor,
  xAxisDefaults,
  yAxisDefaults,
} from "./_chart-axis";
import { formatPtBr } from "../../lib/date";

type CandleBar = StockOhlc["bars"][number] & {
  prevClose: number | null;
  pctVsPrev: number | null;
  isSelected: boolean;
};

const UP_COLOR = "hsl(var(--sentiment-positive))";
const DOWN_COLOR = "hsl(var(--sentiment-negative))";
const SELECTED_STROKE = "hsl(var(--primary))";

export type StockCandleChartProps = {
  data: StockOhlc;
};

export function StockCandleChart({ data }: StockCandleChartProps) {
  if (!data.bars.length) {
    return <EmptyTile label="— sem cotação —" />;
  }
  const bars: CandleBar[] = data.bars.map((b, i, arr) => {
    const prev = i > 0 ? arr[i - 1].close : null;
    const pct = prev !== null && prev !== 0 ? ((b.close - prev) / prev) * 100 : null;
    return {
      ...b,
      prevClose: prev,
      pctVsPrev: pct,
      isSelected: b.date === data.selectedDate,
    };
  });

  const lows = bars.map((b) => b.low);
  const highs = bars.map((b) => b.high);
  const minY = Math.min(...lows);
  const maxY = Math.max(...highs);
  const pad = (maxY - minY) * 0.05 || maxY * 0.01 || 1;

  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={bars} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <XAxis
            dataKey="date"
            tickFormatter={formatDateTick}
            interval="preserveStartEnd"
            minTickGap={16}
            {...xAxisDefaults}
          />
          <YAxis
            width={48}
            domain={[minY - pad, maxY + pad]}
            tickFormatter={(v: number) => v.toFixed(2)}
            {...yAxisDefaults}
          />
          <Tooltip cursor={tooltipCursor} content={<CandleTooltip />} />
          {/* Transparent driver series so the band scale + tooltip have something to hit. */}
          <RechartsBar dataKey="close" fill="transparent" isAnimationActive={false} />
          <Customized component={CandleLayer as never} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function CandleLayer(props: { xAxisMap?: Record<string, AxisInternal>; yAxisMap?: Record<string, AxisInternal>; data?: CandleBar[] }) {
  const { xAxisMap, yAxisMap, data: bars } = props;
  if (!xAxisMap || !yAxisMap || !bars) return null;
  const xAxis = Object.values(xAxisMap)[0];
  const yAxis = Object.values(yAxisMap)[0];
  if (!xAxis?.scale || !yAxis?.scale) return null;

  const band =
    typeof xAxis.bandSize === "number" && xAxis.bandSize > 0
      ? xAxis.bandSize
      : typeof xAxis.scale.bandwidth === "function"
        ? xAxis.scale.bandwidth()
        : 8;
  const bodyW = Math.max(2, band * 0.6);

  return (
    <g pointerEvents="none">
      {bars.map((b) => {
        const cxRaw = xAxis.scale(b.date);
        if (cxRaw == null) return null;
        const cx =
          typeof xAxis.scale.bandwidth === "function"
            ? cxRaw + xAxis.scale.bandwidth() / 2
            : cxRaw;
        const yHigh = yAxis.scale(b.high);
        const yLow = yAxis.scale(b.low);
        const yOpen = yAxis.scale(b.open);
        const yClose = yAxis.scale(b.close);
        if (yHigh == null || yLow == null || yOpen == null || yClose == null) return null;
        const up = b.close >= b.open;
        const fill = up ? UP_COLOR : DOWN_COLOR;
        const yTop = Math.min(yOpen, yClose);
        const yBot = Math.max(yOpen, yClose);
        return (
          <g key={b.date}>
            <line x1={cx} x2={cx} y1={yHigh} y2={yLow} stroke={fill} strokeWidth={1} />
            <rect
              x={cx - bodyW / 2}
              y={yTop}
              width={bodyW}
              height={Math.max(1, yBot - yTop)}
              fill={fill}
              stroke={b.isSelected ? SELECTED_STROKE : fill}
              strokeWidth={b.isSelected ? 1.5 : 1}
            />
          </g>
        );
      })}
    </g>
  );
}

type AxisInternal = {
  bandSize?: number;
  scale: ((value: unknown) => number | undefined) & { bandwidth?: () => number };
};

function CandleTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: CandleBar }>;
}) {
  if (!active || !payload?.length) return null;
  const b = payload[0].payload;
  const pct = b.pctVsPrev;
  const pctColor =
    pct === null
      ? "text-muted-foreground/80"
      : pct >= 0
        ? "text-[color:hsl(var(--sentiment-positive))]"
        : "text-[color:hsl(var(--sentiment-negative))]";
  return (
    <TooltipShell>
      <div className="uppercase tracking-widest text-muted-foreground/80">
        {formatPtBr(b.date)}
      </div>
      <div className="grid grid-cols-2 gap-x-3 mt-1 tabular-nums">
        <span className="text-muted-foreground">O</span>
        <span className="text-right">{b.open.toFixed(2)}</span>
        <span className="text-muted-foreground">H</span>
        <span className="text-right">{b.high.toFixed(2)}</span>
        <span className="text-muted-foreground">L</span>
        <span className="text-right">{b.low.toFixed(2)}</span>
        <span className="text-muted-foreground">C</span>
        <span className="text-right">{b.close.toFixed(2)}</span>
      </div>
      <div className={`mt-1 tabular-nums ${pctColor}`}>
        {pct === null ? "— vs prev —" : `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}% vs prev`}
      </div>
    </TooltipShell>
  );
}

function formatDateTick(iso: string): string {
  // ``YYYY-MM-DD`` → ``DD/MM`` for tighter axis labels.
  const parts = iso.split("-");
  if (parts.length !== 3) return iso;
  return `${parts[2]}/${parts[1]}`;
}
