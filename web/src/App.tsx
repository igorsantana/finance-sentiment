import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, PlayCircle } from "lucide-react";
import { Button } from "./components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./components/ui/card";
import { Calendar } from "./components/ui/calendar";
import { Progress } from "./components/ui/progress";
import { ScrollArea } from "./components/ui/scroll-area";
import {
  DatesPayload,
  StreamEvent,
  getDates,
  openStream,
  startRun,
  toIsoDate,
} from "./api";

type LogLine = { level: string; logger: string; message: string };

const STAGE_LABEL: Record<string, string> = {
  ingest: "Ingest",
  extract: "Extract",
  render: "Render",
};

export default function App() {
  const [dates, setDates] = useState<DatesPayload>({
    processed: [],
    with_articles: [],
  });
  const [selected, setSelected] = useState<Date | undefined>(new Date());
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [stage, setStage] = useState<string>("");
  const [pct, setPct] = useState(0);
  const [running, setRunning] = useState(false);
  const [final, setFinal] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const logEndRef = useRef<HTMLDivElement | null>(null);

  const refreshDates = () =>
    getDates().then(setDates).catch((e) => console.error(e));

  useEffect(() => {
    refreshDates();
    return () => {
      esRef.current?.close();
    };
  }, []);

  // Auto-scroll the log area as new lines arrive.
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [logs.length]);

  const processedSet = useMemo(
    () => new Set(dates.processed),
    [dates.processed],
  );
  const articleSet = useMemo(
    () => new Set(dates.with_articles),
    [dates.with_articles],
  );

  const handleStart = async () => {
    if (!selected || running) return;
    const iso = toIsoDate(selected);
    setLogs([]);
    setStage("");
    setPct(0);
    setFinal(null);
    setRunning(true);
    try {
      const { stream_url } = await startRun(iso);
      esRef.current = openStream(
        stream_url,
        (ev: StreamEvent) => {
          if (ev.type === "log") {
            setLogs((L) => [
              ...L,
              { level: ev.level, logger: ev.logger, message: ev.message },
            ]);
          } else if (ev.type === "progress") {
            setStage(ev.stage);
            const p =
              ev.total > 0 ? Math.round((100 * ev.current) / ev.total) : 0;
            setPct(p);
          } else if (ev.type === "done") {
            setStage("done");
            setPct(100);
            setFinal(
              `Concluído — ${ev.n_fetched} novos artigos, ${ev.n_extracted} extraídos.`,
            );
            setRunning(false);
            esRef.current?.close();
            refreshDates();
          } else if (ev.type === "error") {
            setStage("error");
            setFinal(`Erro: ${ev.message}`);
            setRunning(false);
            esRef.current?.close();
          }
        },
        () => setRunning(false),
      );
    } catch (e) {
      setFinal(`Erro: ${String(e)}`);
      setRunning(false);
    }
  };

  return (
    <main className="min-h-screen bg-muted/30">
      <div className="mx-auto max-w-6xl px-6 py-8">
        <header className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight">Finance News</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Selecione uma data e acompanhe a execução do pipeline em tempo real.
          </p>
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-[auto,1fr] gap-6 items-start">
          <Card>
            <CardHeader>
              <CardTitle>Calendário</CardTitle>
              <CardDescription>
                <span className="inline-flex items-center gap-1.5 mr-3">
                  <span className="h-2 w-2 rounded-full bg-emerald-500" />
                  processado
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-blue-400" />
                  com artigos
                </span>
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Calendar
                mode="single"
                selected={selected}
                onSelect={setSelected}
                modifiers={{
                  processed: (d) => processedSet.has(toIsoDate(d)),
                  hasArticles: (d) =>
                    articleSet.has(toIsoDate(d)) &&
                    !processedSet.has(toIsoDate(d)),
                }}
                modifiersClassNames={{
                  processed:
                    "bg-emerald-100 text-emerald-900 font-semibold hover:bg-emerald-200",
                  hasArticles: "ring-1 ring-blue-300",
                }}
              />
              <div className="mt-4 flex flex-col gap-2">
                <div className="text-sm">
                  <span className="text-muted-foreground">Selecionada: </span>
                  <span className="font-mono">
                    {selected ? toIsoDate(selected) : "—"}
                  </span>
                </div>
                <Button
                  onClick={handleStart}
                  disabled={!selected || running}
                  className="w-full"
                >
                  {running ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Executando…
                    </>
                  ) : (
                    <>
                      <PlayCircle className="mr-2 h-4 w-4" />
                      Executar pipeline
                    </>
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card className="overflow-hidden">
            <CardHeader>
              <div className="flex items-center justify-between gap-4">
                <div>
                  <CardTitle>
                    {stage
                      ? `Progresso — ${STAGE_LABEL[stage] ?? stage}`
                      : "Progresso"}
                  </CardTitle>
                  <CardDescription>
                    {final ?? "Aguardando início da execução."}
                  </CardDescription>
                </div>
                <div className="text-2xl font-mono tabular-nums">{pct}%</div>
              </div>
              <div className="pt-3">
                <Progress value={pct} />
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
                Logs (info)
              </div>
              <ScrollArea className="h-[460px] rounded-md border bg-background">
                <div className="p-3 font-mono text-xs leading-5">
                  {logs.length === 0 ? (
                    <div className="text-muted-foreground">
                      Os logs aparecerão aqui durante a execução.
                    </div>
                  ) : (
                    logs.map((l, i) => (
                      <div
                        key={i}
                        className={
                          l.level === "WARNING" || l.level === "ERROR"
                            ? "text-amber-600"
                            : "text-foreground"
                        }
                      >
                        {l.message}
                      </div>
                    ))
                  )}
                  <div ref={logEndRef} />
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </div>
      </div>
    </main>
  );
}
