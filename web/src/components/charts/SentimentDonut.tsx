import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { ReportPayload } from "../../api";
import { ChartCard } from "./ChartCard";
import {
  SENTIMENT_COLORS,
  SENTIMENT_LABEL_PT,
  type SentimentTone,
} from "../../lib/sentiment";
import { TooltipShell } from "./_chart-axis";

const ORDER: SentimentTone[] = ["positive", "neutral", "negative"];

type SliceDatum = { tone: SentimentTone; label: string; value: number };

function DonutTooltip({
  active,
  payload,
  total,
}: {
  active?: boolean;
  payload?: Array<{ payload: SliceDatum }>;
  total: number;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const share = total ? Math.round((100 * d.value) / total) : 0;
  return (
    <TooltipShell>
      <div className="uppercase tracking-widest text-muted-foreground/80">
        {d.label}
      </div>
      <div
        className="text-base font-bold tabular-nums"
        style={{ color: SENTIMENT_COLORS[d.tone] }}
      >
        {d.value} <span className="text-muted-foreground/70">· {share}%</span>
      </div>
    </TooltipShell>
  );
}

export function SentimentDonut({ data }: { data: ReportPayload }) {
  const slices: SliceDatum[] = ORDER.map((tone) => ({
    tone,
    label: SENTIMENT_LABEL_PT[tone],
    value: data.counts.bySentiment[tone],
  }));
  const total = data.counts.total;

  return (
    <ChartCard title="Distribuição de sentimento" subtitle={`${total} artigos`}>
      <div className="relative h-56">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={slices}
              dataKey="value"
              nameKey="label"
              innerRadius="60%"
              outerRadius="80%"
              stroke="hsl(var(--card))"
              strokeWidth={2}
              startAngle={90}
              endAngle={-270}
            >
              {slices.map((s) => (
                <Cell key={s.tone} fill={SENTIMENT_COLORS[s.tone]} />
              ))}
            </Pie>
            <Tooltip
              cursor={false}
              content={<DonutTooltip total={total} />}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <div className="font-mono text-2xl font-bold tabular-nums">
            {total}
          </div>
          <div className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70">
            artigos
          </div>
        </div>
      </div>
      <div className="mt-3 flex items-center justify-center gap-4 text-xs font-mono">
        {slices.map((s) => (
          <span key={s.tone} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: SENTIMENT_COLORS[s.tone] }}
            />
            <span className="uppercase tracking-widest text-muted-foreground/80">
              {s.label}
            </span>
            <span className="tabular-nums text-foreground">{s.value}</span>
          </span>
        ))}
      </div>
    </ChartCard>
  );
}
