import * as React from "react";
import { SENTIMENT_COLORS } from "../../lib/sentiment";

export const tickStyle = {
  fill: "hsl(var(--muted-foreground))",
  fontSize: 10,
  fontFamily: "ui-monospace",
} as const;

export const xAxisDefaults = {
  tick: tickStyle,
  axisLine: false as const,
  tickLine: false as const,
} as const;

export const yAxisDefaults = {
  tick: { ...tickStyle, fill: "hsl(var(--foreground))" },
  axisLine: false as const,
  tickLine: false as const,
} as const;

export const tooltipCursor = { fill: "hsl(var(--muted) / 0.3)" } as const;

export function TooltipShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2 shadow-md text-xs font-mono border-t-2 border-t-primary">
      {children}
    </div>
  );
}

export function SentimentBreakdown({
  positive,
  neutral,
  negative,
}: {
  positive: number;
  neutral: number;
  negative: number;
}) {
  return (
    <div className="mt-1 tabular-nums">
      <span style={{ color: SENTIMENT_COLORS.positive }}>+{positive}</span>
      {" / "}
      <span style={{ color: SENTIMENT_COLORS.neutral }}>={neutral}</span>
      {" / "}
      <span style={{ color: SENTIMENT_COLORS.negative }}>−{negative}</span>
    </div>
  );
}

export function EmptyTile({ label = "— sem dados —" }: { label?: string }) {
  return (
    <div className="text-xs text-muted-foreground/70 font-mono py-8 text-center">
      {label}
    </div>
  );
}
