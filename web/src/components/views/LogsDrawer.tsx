import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { ScrollArea } from "@cyberdeck/ui";
import type { LogLine } from "../../hooks/useRunStream";

const LEVEL_ICON: Record<string, string> = {
  INFO: "ℹ",
  WARNING: "⚠",
  ERROR: "❌",
  DEBUG: "🔍",
};

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => String(n).padStart(2, "0"))
    .join(":");
}

export type LogsDrawerProps = {
  open: boolean;
  onClose: () => void;
  logs: LogLine[];
  final: string | null;
};

export function LogsDrawer({ open, onClose, logs, final }: LogsDrawerProps) {
  const logEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (open) {
      logEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [logs.length, open]);

  return (
    <>
      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-background/40 backdrop-blur-sm"
          onClick={onClose}
        />
      )}

      {/* Drawer panel */}
      <div
        className={`fixed top-0 right-0 h-full w-[480px] z-50 bg-background border-l border-border flex flex-col shadow-2xl transition-transform duration-300 ease-in-out ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border/60">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono uppercase tracking-widest text-foreground/70">
              Logs
            </span>
            <span className="text-[10px] font-mono text-muted-foreground/60">
              ({logs.length})
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded hover:bg-muted/40 transition-colors"
            aria-label="Fechar logs"
          >
            <X className="h-4 w-4 text-muted-foreground" />
          </button>
        </div>

        {final && (
          <div className="px-5 py-3 border-b border-border/40 text-xs font-mono text-muted-foreground bg-muted/20">
            {final}
          </div>
        )}

        <ScrollArea className="flex-1 px-5 py-3">
          <div className="font-mono text-xs leading-5">
            {logs.length === 0 ? (
              <div className="text-muted-foreground/50 pt-4">
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
                    <span className="whitespace-pre-wrap break-all">
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
    </>
  );
}
