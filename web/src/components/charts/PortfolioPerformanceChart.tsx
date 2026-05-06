import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { formatPtBr } from "../../lib/date";

export type PerformanceSeries = {
  ticker: string;
  color: string;
  points: { date: string; close: number | null }[];
};

type ChartPoint = { date: string; [ticker: string]: number | null | string };

const COLORS = [
  "hsl(186 100% 55%)",
  "hsl(320 100% 60%)",
  "hsl(60 100% 55%)",
  "hsl(160 100% 45%)",
  "hsl(280 100% 65%)",
];

export function PortfolioPerformanceChart({
  series,
  quantities,
  mode,
}: {
  series: PerformanceSeries[];
  quantities: Record<string, number>;
  mode: "value" | "pct";
}) {
  // Build chart data — forward-fill close on non-trading days
  const allDates = [
    ...new Set(series.flatMap((s) => s.points.map((p) => p.date))),
  ].sort();

  const filled: Record<string, Record<string, number | null>> = {};
  for (const s of series) {
    let last: number | null = null;
    for (const date of allDates) {
      const found = s.points.find((p) => p.date === date);
      if (found?.close != null) last = found.close;
      if (!filled[date]) filled[date] = {};
      filled[date][s.ticker] = last;
    }
  }

  // Baseline: first date where all series have data
  const baseline: Record<string, number> = {};
  for (const date of allDates) {
    const allPresent = series.every((s) => filled[date][s.ticker] != null);
    if (allPresent) {
      for (const s of series) {
        if (!(s.ticker in baseline)) baseline[s.ticker] = filled[date][s.ticker]!;
      }
      if (Object.keys(baseline).length === series.length) break;
    }
  }

  const rows: ChartPoint[] = allDates.map((date) => {
    const row: ChartPoint = { date };
    let portfolioValue = 0;
    let portfolioBase = 0;
    let hasPortfolio = true;

    for (const s of series) {
      const close = filled[date][s.ticker];
      const base = baseline[s.ticker];

      if (mode === "pct") {
        row[s.ticker] = close != null && base ? ((close - base) / base) * 100 : null;
      } else {
        row[s.ticker] = close != null && base ? ((close - base) / base) * 100 : null;
      }

      const qty = quantities[s.ticker] ?? 0;
      if (qty > 0) {
        if (close == null) { hasPortfolio = false; }
        else {
          portfolioValue += qty * close;
          portfolioBase += qty * (base ?? close);
        }
      }
    }

    const hasQty = series.some((s) => (quantities[s.ticker] ?? 0) > 0);
    if (hasQty && hasPortfolio && portfolioBase > 0) {
      row["__portfolio__"] = ((portfolioValue - portfolioBase) / portfolioBase) * 100;
    } else if (hasQty) {
      row["__portfolio__"] = null;
    }

    return row;
  });

  const hasQty = series.some((s) => (quantities[s.ticker] ?? 0) > 0);

  const fmt = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <XAxis
          dataKey="date"
          tickFormatter={(d) => formatPtBr(d)}
          tick={{ fontSize: 10, fontFamily: "monospace", fill: "hsl(var(--muted-foreground))" }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tickFormatter={fmt}
          tick={{ fontSize: 10, fontFamily: "monospace", fill: "hsl(var(--muted-foreground))" }}
          axisLine={false}
          tickLine={false}
          width={56}
        />
        <Tooltip
          contentStyle={{
            background: "hsl(var(--background))",
            border: "1px solid hsl(var(--border))",
            borderRadius: 6,
            fontSize: 11,
            fontFamily: "monospace",
          }}
          formatter={(value: number, name: string) => [
            value != null ? fmt(value) : "—",
            name === "__portfolio__" ? "Carteira" : name,
          ]}
          labelFormatter={(label) => formatPtBr(String(label))}
        />
        <ReferenceLine y={0} stroke="hsl(var(--border))" strokeDasharray="3 3" />

        {series.map((s, i) => (
          <Line
            key={s.ticker}
            type="monotone"
            dataKey={s.ticker}
            stroke={COLORS[i % COLORS.length]}
            strokeWidth={1.5}
            dot={false}
            connectNulls
          />
        ))}

        {hasQty && (
          <Line
            key="__portfolio__"
            type="monotone"
            dataKey="__portfolio__"
            stroke="hsl(var(--foreground))"
            strokeWidth={2.5}
            dot={false}
            connectNulls
            strokeDasharray="4 2"
          />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}
