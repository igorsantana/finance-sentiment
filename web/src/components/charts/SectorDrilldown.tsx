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
} from "./_chart-axis";

const STACK: SentimentTone[] = ["positive", "neutral", "negative"];

type Datum = ReportPayload["sectorMatrix"][number];

function DrilldownTooltip({
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
        {d.sector}
      </div>
      <SentimentBreakdown {...d} />
      <div className="mt-1 text-muted-foreground/80">
        total {total} · saldo {(d.tilt * 100).toFixed(0)}%
      </div>
      {d.topCompanies.length > 0 ? (
        <div className="mt-1 text-muted-foreground/80">
          ▸ {d.topCompanies.join(", ")}
        </div>
      ) : null}
    </TooltipShell>
  );
}

type TickPayload = { value: string; index: number };

function DualLineTick(
  topByLabel: Map<string, string[]>,
): (props: {
  x?: number;
  y?: number;
  payload?: TickPayload;
}) => React.ReactElement {
  const Tick = (props: { x?: number; y?: number; payload?: TickPayload }) => {
    const { x = 0, y = 0, payload } = props;
    const label = payload?.value ?? "";
    const top = topByLabel.get(label) ?? [];
    const meta = top.length > 0 ? `▸ ${top.join(", ")}` : "";
    return (
      <g transform={`translate(${x},${y})`}>
        <text
          x={-6}
          y={-4}
          textAnchor="end"
          fill="hsl(var(--foreground))"
          fontSize={10}
          fontFamily="ui-monospace"
        >
          {label}
        </text>
        {meta ? (
          <text
            x={-6}
            y={9}
            textAnchor="end"
            fill="hsl(var(--muted-foreground))"
            fontSize={9}
            fontFamily="ui-monospace"
          >
            {meta}
          </text>
        ) : null}
      </g>
    );
  };
  return Tick;
}

export function SectorDrilldown({ data }: { data: ReportPayload }) {
  const rows = data.sectorMatrix
    .slice()
    .sort((a, b) => b.tilt - a.tilt)
    .reverse();

  const topByLabel = new Map(rows.map((r) => [r.sector, r.topCompanies]));

  return (
    <ChartCard
      title="Setores com empresas-chave"
      subtitle="ordenado por saldo"
    >
      {rows.length === 0 ? (
        <EmptyTile />
      ) : (
        <div style={{ height: Math.max(rows.length * 36, 320) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 16 }}>
              <XAxis type="number" {...xAxisDefaults} />
              <YAxis
                type="category"
                dataKey="sector"
                width={220}
                tickLine={false}
                axisLine={false}
                tick={DualLineTick(topByLabel)}
                interval={0}
              />
              <Tooltip cursor={tooltipCursor} content={<DrilldownTooltip />} />
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
