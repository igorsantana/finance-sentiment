import { useState } from "react";
import { Loader2, PlayCircle } from "lucide-react";
import { Button } from "../ui/button";
import { LogsPanel } from "./LogsPanel";
import type { LogLine } from "../../hooks/useRunStream";

export type PipelineViewProps = {
  runDate: string;
  onRunDateChange: (iso: string) => void;
  running: boolean;
  canRun: boolean;
  final: string | null;
  logs: LogLine[];
  onStart: () => void;
};

export function PipelineView({
  runDate,
  onRunDateChange,
  running,
  canRun,
  final,
  logs,
  onStart,
}: PipelineViewProps) {
  const [logsOpen, setLogsOpen] = useState(false);

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 max-w-2xl space-y-6">
        <div>
          <h2 className="font-mono uppercase tracking-[0.25em] text-xs text-muted-foreground mb-1">
            Pipeline
          </h2>
          <p className="text-2xl font-semibold">Executar processamento</p>
        </div>

        <div className="flex items-end gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-mono uppercase tracking-widest text-muted-foreground">
              Data
            </span>
            <input
              type="date"
              lang="pt-BR"
              value={runDate}
              onChange={(e) => onRunDateChange(e.target.value)}
              disabled={running}
              className="bg-background border border-border rounded-md px-3 py-2 text-sm font-mono focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
            />
          </label>
          <Button onClick={onStart} disabled={!canRun}>
            {running ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Executando…
              </>
            ) : (
              <>
                <PlayCircle className="mr-2 h-4 w-4" />
                Executar
              </>
            )}
          </Button>
        </div>

        {final && (
          <div className="text-sm border border-border rounded-md p-3 bg-muted/30">
            {final}
          </div>
        )}
      </div>

      <div className="-mx-8 mt-8">
        <LogsPanel
          logs={logs}
          open={logsOpen}
          onToggle={() => setLogsOpen((v) => !v)}
        />
      </div>
    </div>
  );
}
