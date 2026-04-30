import { useState } from "react";
import { ChevronDown, Cpu, FileBarChart, Zap } from "lucide-react";

export type Section = "pipeline" | "report";

export type SidebarProps = {
  section: Section;
  reportDate: string | null;
  processedDates: string[];
  onSelectPipeline: () => void;
  onSelectReport: (dateIso: string) => void;
};

export function Sidebar({
  section,
  reportDate,
  processedDates,
  onSelectPipeline,
  onSelectReport,
}: SidebarProps) {
  const [reportsOpen, setReportsOpen] = useState(true);
  const dates = [...processedDates].sort().reverse();

  const baseEntry =
    "w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors";
  const idle = "text-muted-foreground hover:text-foreground hover:bg-muted/40";
  const active = "bg-primary/10 text-primary border neon-edge";

  return (
    <aside className="border-r border-border bg-background/60 backdrop-blur-sm flex flex-col">
      <div className="px-5 py-5 border-b border-border scanline">
        <div className="flex items-center gap-2 font-mono">
          <Zap className="h-4 w-4 text-primary" />
          <span className="text-sm tracking-[0.2em] uppercase text-foreground">
            Finance<span className="text-primary">.News</span>
          </span>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4 flex flex-col gap-1">
        <button
          type="button"
          onClick={onSelectPipeline}
          className={`${baseEntry} ${section === "pipeline" ? active : idle}`}
        >
          <Cpu className="h-4 w-4" />
          <span className="font-mono uppercase tracking-wider text-xs">Pipeline</span>
        </button>

        <button
          type="button"
          onClick={() => setReportsOpen((v) => !v)}
          className={`${baseEntry} ${idle} justify-between`}
        >
          <span className="flex items-center gap-2">
            <FileBarChart className="h-4 w-4" />
            <span className="font-mono uppercase tracking-wider text-xs">Reports</span>
          </span>
          <ChevronDown
            className={`h-3.5 w-3.5 transition-transform ${reportsOpen ? "rotate-0" : "-rotate-90"}`}
          />
        </button>

        {reportsOpen && (
          <div className="ml-2 mt-1 flex flex-col gap-0.5 border-l border-border/60 pl-3">
            {dates.length === 0 ? (
              <div className="text-xs text-muted-foreground/70 px-2 py-1.5 font-mono">
                — sem relatórios —
              </div>
            ) : (
              dates.map((d) => {
                const isActive = section === "report" && reportDate === d;
                return (
                  <button
                    key={d}
                    type="button"
                    onClick={() => onSelectReport(d)}
                    className={`${baseEntry} font-mono text-xs ${
                      isActive ? active : idle
                    }`}
                  >
                    <span className="text-primary/60">▸</span>
                    <span>{d}</span>
                  </button>
                );
              })
            )}
          </div>
        )}
      </nav>

      <div className="px-5 py-3 border-t border-border text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70 flex items-center gap-2">
        <span className="h-1.5 w-1.5 rounded-full bg-primary shadow-[0_0_6px_hsl(var(--primary))]" />
        online
      </div>
    </aside>
  );
}
