import { ChartsPanel } from "./ChartsPanel";
import { ImagesPanel } from "./ImagesPanel";

export type ViewMode = "images" | "charts";

export type ReportViewProps = {
  date: string | null;
  processed: boolean;
  hasArticles: boolean;
  imageBust: string;
  viewMode: ViewMode;
  onViewModeChange: (mode: ViewMode) => void;
};

const TOGGLE_OPTIONS: { id: ViewMode; label: string }[] = [
  { id: "images", label: "Imagens" },
  { id: "charts", label: "Gráficos" },
];

export function ReportView({
  date,
  processed,
  hasArticles,
  imageBust,
  viewMode,
  onViewModeChange,
}: ReportViewProps) {
  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h2 className="font-mono uppercase tracking-[0.25em] text-xs text-muted-foreground mb-1">
            Relatório
          </h2>
          <p className="text-2xl font-semibold font-mono">{date ?? "—"}</p>
        </div>

        <div
          role="tablist"
          aria-label="Modo de visualização"
          className="inline-flex border border-border rounded-md p-0.5 bg-muted/30"
        >
          {TOGGLE_OPTIONS.map((opt) => {
            const active = viewMode === opt.id;
            return (
              <button
                key={opt.id}
                role="tab"
                aria-selected={active}
                onClick={() => onViewModeChange(opt.id)}
                className={`px-3 py-1.5 text-xs font-mono uppercase tracking-widest rounded-sm transition-all ${
                  active
                    ? "bg-primary/15 text-primary border neon-edge"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>

      {viewMode === "images" ? (
        <ImagesPanel
          date={date}
          processed={processed}
          hasArticles={hasArticles}
          imageBust={imageBust}
        />
      ) : (
        <ChartsPanel date={date} />
      )}
    </div>
  );
}
