import { useEffect, useState } from "react";
import { AdminView } from "./components/views/AdminView";
import { AnalysisView } from "./components/views/AnalysisView";
import { PipelineView } from "./components/views/PipelineView";
import { PortfolioView } from "./components/views/PortfolioView";
import { ReportView, type ViewMode } from "./components/views/ReportView";
import { Sidebar, type Section } from "./components/layout/Sidebar";
import { TopBar } from "./components/layout/TopBar";
import { useRunStream } from "./hooks/useRunStream";
import { DatesPayload, getDates } from "./api";

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
  const [dates, setDates] = useState<DatesPayload>({ with_articles: [] });
  const [section, setSection] = useState<Section>("pipeline");
  const [reportDate, setReportDate] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("charts");
  const [runDate, setRunDate] = useState<string>(() => todayInSP());

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

  const refreshDates = () =>
    getDates().then(setDates).catch((e) => console.error(e));

  const { running, stage, stageProgress, logs, final, start } = useRunStream({
    onSettled: (outcome) => {
      if (outcome === "ok") {
        refreshDates();
      }
    },
    onReattach: (active) => {
      setRunDate(active.target_date);
      setSection("pipeline");
    },
  });

  useEffect(() => {
    refreshDates();
  }, []);

  const canRun = !running && /^\d{4}-\d{2}-\d{2}$/.test(runDate);

  const handleStart = () => {
    if (!canRun) return;
    start(runDate, "full");
  };

  const handleSelectReport = (dateIso: string) => {
    setReportDate(dateIso);
    setSection("report");
  };

  return (
    <main className="min-h-screen bg-background grid grid-cols-[260px,1fr]">
      <Sidebar
        section={section}
        reportDate={reportDate}
        reportDates={dates.with_articles}
        portfolioTickers={portfolioTickers}
        onSelectPipeline={() => setSection("pipeline")}
        onSelectReport={handleSelectReport}
        onSelectAnalysis={() => setSection("analysis")}
        onSelectPortfolio={() => setSection("portfolio")}
        onSelectAdmin={() => setSection("admin")}
      />

      <div className="flex flex-col min-h-screen overflow-x-hidden">
        <TopBar running={running} stage={stage} stageProgress={stageProgress} />

        <div className="flex-1 px-8 py-8 min-w-0">
          {section === "admin" ? (
            <AdminView
              portfolioTickers={portfolioTickers}
              onPortfolioChange={setPortfolioTickers}
              quantities={quantities}
              onQtyChange={setQty}
              avgPrices={avgPrices}
              onAvgChange={setAvg}
            />
          ) : section === "pipeline" ? (
            <PipelineView
              runDate={runDate}
              onRunDateChange={setRunDate}
              running={running}
              canRun={canRun}
              final={final}
              logs={logs}
              onStart={handleStart}
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
      </div>
    </main>
  );
}
