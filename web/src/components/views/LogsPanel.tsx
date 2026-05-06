import { useEffect, useRef } from "react";
import { ScrollArea } from "../ui/scroll-area";
import type { LogLine } from "../../hooks/useRunStream";

const LEVEL_ICON: Record<string, string> = {
  INFO: "ℹ",
  WARNING: "⚠",
  ERROR: "❌",
  DEBUG: "🔍",
};

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

export type LogsPanelProps = {
  logs: LogLine[];
};

export function LogsPanel({ logs }: LogsPanelProps) {
  const logEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [logs.length]);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-xs font-mono uppercase tracking-widest text-foreground/70">
          Logs
        </span>
        <span className="text-[10px] text-muted-foreground font-mono">
          ({logs.length})
        </span>
      </div>
      <div className="border-b border-border/40 mb-2" />
      <ScrollArea className="h-[calc(100vh-320px)] min-h-[200px]">
        <div className="font-mono text-xs leading-5 pr-2">
          {logs.length === 0 ? (
            <div className="text-muted-foreground/60">
              Os logs aparecerão aqui durante a execução.
            </div>
          ) : (
            logs.map((l, i) => {
              const icon = LEVEL_ICON[l.level] ?? "•";
              const tone =
                l.level === "ERROR"
                  ? "text-red-500"
                  : l.level === "WARNING"
                    ? "text-amber-500"
                    : "text-foreground/80";
              return (
                <div key={i} className="flex items-start gap-2 py-0.5">
                  <span className={`${tone} inline-block w-5 text-center shrink-0`}>
                    {icon}
                  </span>
                  <span className="whitespace-pre-wrap">
                    <span className="text-muted-foreground">[{formatTime(l.ts)}]</span>{" "}
                    <span className="font-semibold">{l.logger}:</span>{" "}
                    <span className={tone}>{l.message}</span>
                  </span>
                </div>
              );
            })
          )}
          <div ref={logEndRef} />
        </div>
      </ScrollArea>
    </div>
  );
}
