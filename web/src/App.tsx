import { useEffect, useState } from "react";
import { PipelineView } from "./components/PipelineView";
import { ReportView, type ViewMode } from "./components/ReportView";
import { Sidebar, type Section } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
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

export default function App() {
  const [dates, setDates] = useState<DatesPayload>({ with_articles: [] });
  const [section, setSection] = useState<Section>("pipeline");
  const [reportDate, setReportDate] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("charts");
  const [runDate, setRunDate] = useState<string>(() => todayInSP());

  const refreshDates = () =>
    getDates().then(setDates).catch((e) => console.error(e));

  const { running, stage, stageProgress, logs, final, start } = useRunStream({
    onSettled: (outcome) => {
      if (outcome === "ok") {
        refreshDates();
      }
    },
    onReattach: (active) => {
      // A run that started before this tab opened — surface it on Pipeline so
      // logs and the stepper are immediately in view.
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
        onSelectPipeline={() => setSection("pipeline")}
        onSelectReport={handleSelectReport}
      />

      <div className="flex flex-col min-h-screen">
        <TopBar running={running} stage={stage} stageProgress={stageProgress} />

        <div className="flex-1 px-8 py-8">
          {section === "pipeline" ? (
            <PipelineView
              runDate={runDate}
              onRunDateChange={setRunDate}
              running={running}
              canRun={canRun}
              final={final}
              logs={logs}
              onStart={handleStart}
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
