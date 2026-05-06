import { Briefcase, CalendarDays, LineChart, ShieldCheck, Zap } from "lucide-react";
import { formatPtBr } from "../../lib/date";

export type Section = "pipeline" | "report" | "analysis" | "portfolio" | "admin" | "calendar";

export type SidebarProps = {
  section: Section;
  reportDate: string | null;
  portfolioTickers: string[];
  onSelectCalendar: () => void;
  onSelectAnalysis: () => void;
  onSelectPortfolio: () => void;
  onSelectAdmin: () => void;
};

export function Sidebar({
  section,
  reportDate,
  portfolioTickers,
  onSelectCalendar,
  onSelectAnalysis,
  onSelectPortfolio,
  onSelectAdmin,
}: SidebarProps) {
  const baseEntry =
    "w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors";
  const idle = "text-muted-foreground hover:text-foreground hover:bg-muted/40";
  const active = "bg-primary/10 text-primary border neon-edge";

  const calActive = section === "calendar" || section === "report";

  return (
    <aside className="border-r border-border bg-background/60 backdrop-blur-sm flex flex-col">
      <div className="px-5 py-5 border-b border-border scanline">
        <div className="flex items-center gap-2 font-mono">
          <Zap className="h-4 w-4 text-primary neon-flicker" />
          <span className="text-sm tracking-[0.2em] uppercase text-foreground">
            Finance<span className="text-primary">.News</span>
          </span>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4 flex flex-col gap-1">
        <button
          type="button"
          onClick={onSelectCalendar}
          className={`${baseEntry} ${calActive ? active : idle}`}
        >
          <CalendarDays className="h-4 w-4" />
          <span className="font-mono uppercase tracking-wider text-xs">Calendário</span>
          {reportDate && (
            <span className="ml-auto text-[10px] font-mono text-primary/70 truncate max-w-[80px]">
              {formatPtBr(reportDate)}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={onSelectAnalysis}
          className={`${baseEntry} ${section === "analysis" ? active : idle}`}
        >
          <LineChart className="h-4 w-4" />
          <span className="font-mono uppercase tracking-wider text-xs">Análise</span>
        </button>

        <button
          type="button"
          onClick={onSelectPortfolio}
          className={`${baseEntry} ${section === "portfolio" ? active : idle}`}
        >
          <Briefcase className="h-4 w-4" />
          <span className="font-mono uppercase tracking-wider text-xs">Carteira</span>
          {portfolioTickers.length > 0 && (
            <span className="ml-auto text-[10px] font-mono text-primary/70">
              {portfolioTickers.length}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={onSelectAdmin}
          className={`${baseEntry} ${section === "admin" ? active : idle}`}
        >
          <ShieldCheck className="h-4 w-4" />
          <span className="font-mono uppercase tracking-wider text-xs">Admin</span>
        </button>
      </nav>

      <div className="px-5 py-3 border-t border-border text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70 flex items-center gap-2">
        <span className="relative flex h-2 w-2">
          <span
            className="absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"
            style={{ animation: "live-ring 1.8s ease-out infinite" }}
          />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-primary shadow-[0_0_6px_hsl(var(--primary))]" />
        </span>
        <span>online</span>
      </div>
    </aside>
  );
}
