import type { StageProgress } from "../hooks/useRunStream";

const STAGES = [
  { id: "ingest", label: "Buscar", icon: "🔍" },
  { id: "extract", label: "Extrair", icon: "⚡" },
  { id: "render", label: "Render", icon: "🎨" },
];

export type TopBarProps = {
  running: boolean;
  stage: string;
  stageProgress: StageProgress;
};

export function TopBar({ running, stage, stageProgress }: TopBarProps) {
  const currentStageIndex = STAGES.findIndex((s) => s.id === stage);
  const isDone = stage === "done";
  const isError = stage === "error";

  const stageFrac =
    stageProgress.total > 0
      ? Math.min(stageProgress.current / stageProgress.total, 1)
      : 0;
  const progressPercent =
    isDone
      ? 100
      : stage === "" || currentStageIndex < 0
        ? 0
        : Math.round(((currentStageIndex + stageFrac) / STAGES.length) * 100);

  return (
    <div className="border-b border-border bg-background/80 backdrop-blur-sm scanline">
      <div className="px-6 py-4">
        <div className="flex items-center justify-center gap-3 mb-3">
          {STAGES.map((s, idx) => {
            const completed = isDone || (!isError && idx < currentStageIndex);
            const active = !isDone && !isError && idx === currentStageIndex;
            const errored = isError && idx === currentStageIndex;
            const circleClass = errored
              ? "bg-destructive text-destructive-foreground border border-destructive"
              : active
                ? "bg-primary text-primary-foreground border neon-edge"
                : completed
                  ? "bg-primary/15 text-primary border border-primary/60"
                  : "bg-muted/40 text-muted-foreground border border-border";
            const labelClass = active
              ? "text-primary"
              : completed
                ? "text-primary/80"
                : errored
                  ? "text-destructive"
                  : "text-muted-foreground";
            const connectorClass =
              isDone || (!isError && idx < currentStageIndex)
                ? "bg-primary/60"
                : "bg-border";
            return (
              <div key={s.id} className="flex items-center gap-3">
                <div
                  className={`flex items-center justify-center w-9 h-9 rounded-full text-sm transition-all ${circleClass}`}
                >
                  {s.icon}
                </div>
                <div
                  className={`text-[11px] font-mono uppercase tracking-widest ${labelClass}`}
                >
                  {s.label}
                </div>
                {idx < STAGES.length - 1 && (
                  <div className={`w-10 h-px transition-all ${connectorClass}`} />
                )}
              </div>
            );
          })}
        </div>
        <div className="flex items-center gap-3">
          <div className="flex-1 h-1 bg-muted/50 rounded-full overflow-hidden border border-border/60">
            <div
              className={`h-full transition-all duration-300 ${
                isError
                  ? "bg-destructive"
                  : running
                    ? "bg-primary shadow-[0_0_8px_hsl(var(--accent)/0.5)]"
                    : "bg-primary/60"
              }`}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          <div
            className={`w-12 text-right font-mono text-xs tabular-nums ${
              running ? "text-primary" : "text-muted-foreground"
            }`}
          >
            {progressPercent}%
          </div>
        </div>
      </div>
    </div>
  );
}
