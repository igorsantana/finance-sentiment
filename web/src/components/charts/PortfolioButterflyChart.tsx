import { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, ReferenceLine,
  Tooltip, ResponsiveContainer, Cell, LabelList,
} from "recharts";
import { getTrendsCompany, type WindowCompany, type WindowSize } from "../../api";
import { EmptyTile } from "./_chart-axis";

type ButterflyRow = {
  ticker: string;
  positive: number;    // 0–100
  negative: number;    // 0 to –100 (left side)
  neutral: number;
  total: number;
  net: number | null;
};

const POS_COLOR = "hsl(142 70% 45%)";
const NEG_COLOR = "hsl(0 80% 55%)";

function CustomTooltip({ active, payload }: { active?: boolean; payload?: { payload: ButterflyRow }[] }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="bg-background border border-border rounded-md px-3 py-2 text-xs font-mono shadow-xl">
      <p className="font-bold mb-1 text-foreground">{row.ticker}</p>
      <p className="text-emerald-400">pos  {row.positive.toFixed(1)}%</p>
      <p className="text-slate-400">neu  {row.neutral.toFixed(1)}%</p>
      <p className="text-red-400">neg  {Math.abs(row.negative).toFixed(1)}%</p>
      <p className="text-muted-foreground mt-1">{row.total} artigos</p>
    </div>
  );
}

export function PortfolioButterflyChart({
  portfolioTickers,
  windowSize,
}: {
  portfolioTickers: string[];
  windowSize: WindowSize;
}) {
  const [companyData, setCompanyData] = useState<Record<string, WindowCompany>>({});
  const [loading, setLoading] = useState(false);

  const tickersKey = portfolioTickers.join(",");

  useEffect(() => {
    if (portfolioTickers.length === 0) { setCompanyData({}); return; }
    const ctrl = new AbortController();
    setLoading(true);
    Promise.all(
      portfolioTickers.map((t) =>
        getTrendsCompany(t, windowSize, undefined, ctrl.signal).then((d) => ({ t, d }))
      )
    )
      .then((results) => {
        if (ctrl.signal.aborted) return;
        setCompanyData(Object.fromEntries(results.map(({ t, d }) => [t, d])));
      })
      .catch(() => {})
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
  }, [tickersKey, windowSize]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return <div className="h-48 bg-muted/20 rounded animate-pulse" />;
  }

  const rows: ButterflyRow[] = portfolioTickers
    .flatMap((t): ButterflyRow[] => {
      const d = companyData[t];
      if (!d || d.daily.length === 0) return [];
      const latest = d.daily[d.daily.length - 1];
      const total = latest.total ?? 0;
      if (total === 0) return [];
      const posPct = (latest.positive / total) * 100;
      const negPct = (latest.negative / total) * 100;
      return [{
        ticker: t,
        positive: posPct,
        negative: -negPct,
        neutral: 100 - posPct - negPct,
        total,
        net: latest.net ?? null,
      }];
    });

  if (rows.length === 0) {
    return <EmptyTile label="sem dados para hoje" />;
  }

  const barHeight = 36;
  const chartHeight = Math.max(120, rows.length * barHeight + 32);

  return (
    <ResponsiveContainer width="100%" height={chartHeight}>
      <BarChart
        data={rows}
        layout="vertical"
        margin={{ top: 4, right: 16, bottom: 4, left: 0 }}
        barCategoryGap="30%"
      >
        <XAxis
          type="number"
          domain={[-100, 100]}
          tickFormatter={(v) => `${Math.abs(v)}%`}
          tick={{ fontSize: 10, fontFamily: "monospace", fill: "hsl(var(--muted-foreground))" }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          type="category"
          dataKey="ticker"
          width={52}
          tick={{ fontSize: 11, fontFamily: "monospace", fontWeight: 600, fill: "hsl(var(--foreground))" }}
          tickLine={false}
          axisLine={false}
        />
        <ReferenceLine x={0} stroke="hsl(var(--border))" strokeWidth={1} />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: "hsl(var(--muted) / 0.3)" }} />

        {/* Negative bars — go left */}
        <Bar dataKey="negative" stackId="a" fill={NEG_COLOR} radius={[2, 0, 0, 2]}>
          {rows.map((row) => (
            <Cell key={row.ticker} fill={NEG_COLOR} fillOpacity={0.85} />
          ))}
          <LabelList
            dataKey="negative"
            position="insideLeft"
            formatter={(v: number) => Math.abs(v) > 8 ? `${Math.abs(v).toFixed(0)}%` : ""}
            style={{ fontSize: 10, fontFamily: "monospace", fill: "#fff", fontWeight: 600 }}
          />
        </Bar>

        {/* Positive bars — go right */}
        <Bar dataKey="positive" stackId="b" fill={POS_COLOR} radius={[0, 2, 2, 0]}>
          {rows.map((row) => (
            <Cell key={row.ticker} fill={POS_COLOR} fillOpacity={0.85} />
          ))}
          <LabelList
            dataKey="positive"
            position="insideRight"
            formatter={(v: number) => v > 8 ? `${v.toFixed(0)}%` : ""}
            style={{ fontSize: 10, fontFamily: "monospace", fill: "#fff", fontWeight: 600 }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
