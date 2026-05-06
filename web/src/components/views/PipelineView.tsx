import { Loader2, PlayCircle } from "lucide-react";
import { Button } from "../ui/button";

export type PipelineViewProps = {
  runDate: string;
  onRunDateChange: (iso: string) => void;
  running: boolean;
  canRun: boolean;
  final: string | null;
  onStart: () => void;
};

export function PipelineView({
  runDate,
  onRunDateChange,
  running,
  canRun,
  final,
  onStart,
}: PipelineViewProps) {
  return (
    <div className="space-y-6 max-w-2xl">
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
        <div className="text-sm border border-border/40 rounded-md p-3 bg-muted/20 font-mono">
          {final}
        </div>
      )}
    </div>
  );
}
