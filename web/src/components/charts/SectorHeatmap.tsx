import type { ReportPayload } from "../../api";
import { ChartCard } from "./ChartCard";
import { SENTIMENT_LABEL_PT, type SentimentTone } from "../../lib/sentiment";

const COLS: SentimentTone[] = ["positive", "neutral", "negative"];

const ANCHORS: Array<{ stop: number; h: number; s: number; l: number }> = [
  { stop: -1, h: 320, s: 100, l: 60 },
  { stop: -0.5, h: 290, s: 55, l: 58 },
  { stop: 0, h: 240, s: 10, l: 60 },
  { stop: 0.5, h: 200, s: 55, l: 56 },
  { stop: 1, h: 160, s: 100, l: 55 },
];

function tiltColor(tilt: number, alpha = 1): string {
  const t = Math.max(-1, Math.min(1, tilt));
  let lo = ANCHORS[0];
  let hi = ANCHORS[ANCHORS.length - 1];
  for (let i = 0; i < ANCHORS.length - 1; i++) {
    if (t >= ANCHORS[i].stop && t <= ANCHORS[i + 1].stop) {
      lo = ANCHORS[i];
      hi = ANCHORS[i + 1];
      break;
    }
  }
  const span = hi.stop - lo.stop || 1;
  const f = (t - lo.stop) / span;
  const h = lo.h + (hi.h - lo.h) * f;
  const s = lo.s + (hi.s - lo.s) * f;
  const l = lo.l + (hi.l - lo.l) * f;
  return `hsl(${h.toFixed(0)} ${s.toFixed(0)}% ${l.toFixed(0)}% / ${alpha})`;
}

export function SectorHeatmap({ data }: { data: ReportPayload }) {
  const rows = data.sectorMatrix
    .slice()
    .sort(
      (a, b) =>
        b.positive + b.neutral + b.negative - (a.positive + a.neutral + a.negative),
    )
    .slice(0, 15);

  if (rows.length === 0) {
    return (
      <ChartCard title="Mapa de calor — setores">
        <div className="text-xs text-muted-foreground/70 font-mono py-8 text-center">
          — sem dados —
        </div>
      </ChartCard>
    );
  }

  return (
    <ChartCard title="Mapa de calor — setores" subtitle={`top ${rows.length}`}>
      <div className="space-y-1">
        <div
          className="grid items-center gap-1 text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70 pb-1"
          style={{ gridTemplateColumns: "1fr repeat(3, minmax(0, 60px))" }}
        >
          <span />
          {COLS.map((tone) => (
            <span key={tone} className="text-center">
              {SENTIMENT_LABEL_PT[tone]}
            </span>
          ))}
        </div>
        {rows.map((row) => {
          const bg = tiltColor(row.tilt, 0.85);
          return (
            <div
              key={row.sector}
              className="grid items-center gap-1"
              style={{ gridTemplateColumns: "1fr repeat(3, minmax(0, 60px))" }}
            >
              <span
                className="truncate text-xs font-mono pr-2 text-foreground"
                title={row.sector}
              >
                {row.sector}
              </span>
              {COLS.map((tone) => (
                <span
                  key={tone}
                  className="text-center font-mono text-xs tabular-nums rounded-sm py-1.5 transition hover:scale-[1.04] hover:neon-edge"
                  style={{
                    background: bg,
                    color: "hsl(240 18% 6%)",
                  }}
                >
                  {row[tone]}
                </span>
              ))}
            </div>
          );
        })}
      </div>
    </ChartCard>
  );
}
