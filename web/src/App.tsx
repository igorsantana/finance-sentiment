import { useEffect, useState } from "react";
import { AdminView } from "./components/views/AdminView";
import { AnalysisView } from "./components/views/AnalysisView";
import { CalendarView } from "./components/views/CalendarView";
import { LogsDrawer } from "./components/views/LogsDrawer";
import { PortfolioView } from "./components/views/PortfolioView";
import { ReportView, type ViewMode } from "./components/views/ReportView";
import { Sidebar, type Section } from "./components/layout/Sidebar";
import { TopBar } from "./components/layout/TopBar";
import { useRunStream } from "./hooks/useRunStream";

function todayInSP(): string {
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return fmt.format(new Date());
}

function loadStorage<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export default function App() {
  const [section, setSection] = useState<Section>("calendar");
  const [reportDate, setReportDate] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("charts");
  const [runDate, setRunDate] = useState<string>(() => todayInSP());
  const [logsOpen, setLogsOpen] = useState(false);

  const [portfolioTickers, setPortfolioTickersRaw] = useState<string[]>(
    () => loadStorage<string[]>("portfolioTickers", [])
  );
  const [quantities, setQuantitiesRaw] = useState<Record<string, number>>(
    () => loadStorage<Record<string, number>>("portfolioQuantities", {})
  );
  const [avgPrices, setAvgPricesRaw] = useState<Record<string, number>>(
    () => loadStorage<Record<string, number>>("portfolioAvgPrices", {})
  );

  const setPortfolioTickers = (tickers: string[]) => {
    setPortfolioTickersRaw(tickers);
    localStorage.setItem("portfolioTickers", JSON.stringify(tickers));
  };

  const setQty = (root: string, qty: number) => {
    setQuantitiesRaw((prev) => {
      const next = { ...prev, [root]: qty };
      localStorage.setItem("portfolioQuantities", JSON.stringify(next));
      return next;
    });
  };

  const setAvg = (root: string, avg: number) => {
    setAvgPricesRaw((prev) => {
      const next = { ...prev, [root]: avg };
      localStorage.setItem("portfolioAvgPrices", JSON.stringify(next));
      return next;
    });
  };

  const [queue, setQueue] = useState<string[]>([]);

  const { running, stage, stageProgress, logs, final, start, stop } = useRunStream({
    onSettled: () => {},
    onReattach: (active) => {
      setRunDate(active.target_date);
      setLogsOpen(true);
    },
  });

  useEffect(() => {
    if (running) setLogsOpen(true);
  }, [running]);

  // Auto-drain queue: when pipeline finishes and queue has items, start next
  useEffect(() => {
    if (!running && queue.length > 0) {
      const next = queue[0];
      setQueue((q) => q.slice(1));
      setRunDate(next);
      start(next, "full");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  const handleQueueDate = (dateIso: string) => {
    setQueue((q) => {
      if (q.includes(dateIso)) return q.filter((d) => d !== dateIso);
      // If nothing running, start immediately; otherwise enqueue
      if (!running && q.length === 0) {
        setRunDate(dateIso);
        start(dateIso, "full");
        return q;
      }
      return [...q, dateIso];
    });
  };

  const handleRemoveFromQueue = (dateIso: string) => {
    setQueue((q) => q.filter((d) => d !== dateIso));
  };

  const handleSelectReport = (dateIso: string) => {
    setReportDate(dateIso);
    setSection("report");
  };

  return (
    <main className="h-screen bg-background grid grid-cols-[260px,1fr] overflow-hidden">
      <Sidebar
        section={section}
        reportDate={reportDate}
        portfolioTickers={portfolioTickers}
        onSelectCalendar={() => setSection("calendar")}
        onSelectAnalysis={() => setSection("analysis")}
        onSelectPortfolio={() => setSection("portfolio")}
        onSelectAdmin={() => setSection("admin")}
      />

      <div className="flex flex-col h-full overflow-hidden">
        <TopBar
          running={running}
          stage={stage}
          stageProgress={stageProgress}
          logCount={logs.length}
          onToggleLogs={() => setLogsOpen((v) => !v)}
          onStop={stop}
        />

        <div className="flex-1 min-h-0 overflow-hidden">
          {section === "calendar" ? (
            <CalendarView
              onSelectDate={handleSelectReport}
              selectedDate={reportDate}
              onQueueDate={handleQueueDate}
              onRemoveFromQueue={handleRemoveFromQueue}
              queue={queue}
              running={running}
              runningDate={runDate}
              portfolioTickers={portfolioTickers}
              quantities={quantities}
            />
          ) : (
            <div className="h-full overflow-auto px-8 py-8">
              {section === "admin" ? (
                <AdminView
                  portfolioTickers={portfolioTickers}
                  onPortfolioChange={setPortfolioTickers}
                  quantities={quantities}
                  onQtyChange={setQty}
                  avgPrices={avgPrices}
                  onAvgChange={setAvg}
                />
              ) : section === "analysis" ? (
                <AnalysisView />
              ) : section === "portfolio" ? (
                <PortfolioView
                  portfolioTickers={portfolioTickers}
                  quantities={quantities}
                  avgPrices={avgPrices}
                />
              ) : (
                <ReportView
                  date={reportDate}
                  viewMode={viewMode}
                  onViewModeChange={setViewMode}
                />
              )}
            </div>
          )}
        </div>
      </div>

      <LogsDrawer
        open={logsOpen}
        onClose={() => setLogsOpen(false)}
        logs={logs}
        final={final}
      />
    </main>
  );
}
