import type { ReportPayload } from "../../api";
import { ChartCard } from "./ChartCard";

type Tile = {
  label: string;
  value: string;
  tone?: "positive" | "negative" | "default";
};

function pct(part: number, total: number): string {
  if (!total) return "0%";
  return `${Math.round((100 * part) / total)}%`;
}

export function HeaderStats({ data }: { data: ReportPayload }) {
  const { counts } = data;
  const tiles: Tile[] = [
    { label: "artigos", value: String(counts.total) },
    { label: "veículos", value: String(counts.publishers) },
    {
      label: "% positivo",
      value: pct(counts.bySentiment.positive, counts.total),
      tone: "positive",
    },
    {
      label: "% negativo",
      value: pct(counts.bySentiment.negative, counts.total),
      tone: "negative",
    },
  ];

  return (
    <ChartCard title="Resumo" subtitle={data.date} className="lg:col-span-1">
      <div className="grid grid-cols-2 gap-3">
        {tiles.map((t) => (
          <div
            key={t.label}
            className="rounded-md border border-border/60 bg-background/40 px-4 py-3"
          >
            <div
              className="font-mono text-2xl font-bold tabular-nums"
              style={{
                color:
                  t.tone === "positive"
                    ? "hsl(var(--sentiment-positive))"
                    : t.tone === "negative"
                      ? "hsl(var(--sentiment-negative))"
                      : undefined,
              }}
            >
              {t.value}
            </div>
            <div className="mt-1 text-[10px] font-mono uppercase tracking-widest text-muted-foreground/80">
              {t.label}
            </div>
          </div>
        ))}
      </div>
    </ChartCard>
  );
}
