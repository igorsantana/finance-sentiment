import { useEffect, useRef } from "react";
import { ChevronDown } from "lucide-react";
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
  open: boolean;
  onToggle: () => void;
};

export function LogsPanel({ logs, open, onToggle }: LogsPanelProps) {
  const logEndRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll the log area as new lines arrive.
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [logs.length]);

  return (
    <div className="border-t bg-muted/50">
      <button
        onClick={onToggle}
        className="w-full px-6 py-3 flex items-center justify-between hover:bg-muted transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">Logs</span>
          <span className="text-xs text-muted-foreground">({logs.length})</span>
        </div>
        <ChevronDown
          className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="border-t bg-background px-6 py-3">
          <ScrollArea className="h-[200px] rounded-md border bg-background">
            <div className="p-3 font-mono text-xs leading-5">
              {logs.length === 0 ? (
                <div className="text-muted-foreground">
                  Os logs aparecerão aqui durante a execução.
                </div>
              ) : (
                logs.map((l, i) => {
                  const icon = LEVEL_ICON[l.level] ?? "•";
                  const tone =
                    l.level === "ERROR"
                      ? "text-red-600"
                      : l.level === "WARNING"
                        ? "text-amber-600"
                        : "text-foreground";
                  return (
                    <div key={i} className="flex items-start gap-2">
                      <div className={tone}>
                        <span className="inline-block w-5 text-center">{icon}</span>
                      </div>
                      <div className="text-xs font-mono leading-5 whitespace-pre-wrap">
                        <span className="text-muted-foreground">[{formatTime(l.ts)}]</span>{" "}
                        <span className="font-semibold">{l.logger}:</span>{" "}
                        <span className="ml-1">{l.message}</span>
                      </div>
                    </div>
                  );
                })
              )}
              <div ref={logEndRef} />
            </div>
          </ScrollArea>
        </div>
      )}
    </div>
  );
}
