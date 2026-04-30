import { useEffect, useRef, useState } from "react";
import {
  ActiveRun,
  StreamEvent,
  getActiveRun,
  openStream,
  startRun,
} from "../api";

export type LogLine = {
  level: string;
  logger: string;
  ts: number;
  message: string;
};

export type StageProgress = { current: number; total: number };

export type RunOutcome = "ok" | "error";

export type UseRunStreamOptions = {
  // Fires when the SSE stream emits `done` or `error`. Lets the caller
  // refresh dependent state (e.g. /api/dates) and cache-bust image URLs
  // without reaching into the hook's internals.
  onSettled?: (outcome: RunOutcome) => void;
  // Fires once on mount if /api/runs/active reports an in-flight run, so
  // the caller can snap any selected-date state to the run's target.
  onReattach?: (active: ActiveRun) => void;
};

export type UseRunStreamResult = {
  running: boolean;
  stage: string;
  stageProgress: StageProgress;
  logs: LogLine[];
  final: string | null;
  start: (dateIso: string, kind?: "ingest" | "extract" | "full") => Promise<void>;
};

export function useRunStream(opts: UseRunStreamOptions = {}): UseRunStreamResult {
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [stage, setStage] = useState<string>("");
  const [stageProgress, setStageProgress] = useState<StageProgress>({
    current: 0,
    total: 0,
  });
  const [running, setRunning] = useState(false);
  const [final, setFinal] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  // Latest callbacks via refs so attachStream's closure isn't stale and we
  // don't have to re-attach the SSE source when the parent re-renders.
  const onSettledRef = useRef(opts.onSettled);
  const onReattachRef = useRef(opts.onReattach);
  useEffect(() => {
    onSettledRef.current = opts.onSettled;
    onReattachRef.current = opts.onReattach;
  }, [opts.onSettled, opts.onReattach]);

  const attachStream = (streamUrl: string) => {
    esRef.current?.close();
    setLogs([]);
    setStage("");
    setStageProgress({ current: 0, total: 0 });
    setFinal(null);
    setRunning(true);
    esRef.current = openStream(
      streamUrl,
      (ev: StreamEvent) => {
        if (ev.type === "log") {
          setLogs((L) => [
            ...L,
            { level: ev.level, logger: ev.logger, ts: ev.ts, message: ev.message },
          ]);
        } else if (ev.type === "progress") {
          setStage(ev.stage);
          setStageProgress({ current: ev.current, total: ev.total });
        } else if (ev.type === "done") {
          setStage("done");
          setFinal(
            `Concluído — ${ev.n_fetched} novos artigos, ${ev.n_extracted} extraídos.`,
          );
          setRunning(false);
          esRef.current?.close();
          onSettledRef.current?.("ok");
        } else if (ev.type === "error") {
          setStage("error");
          setFinal(`Erro: ${ev.message}`);
          setRunning(false);
          esRef.current?.close();
          onSettledRef.current?.("error");
        }
      },
      () => setRunning(false),
    );
  };

  // Reattach to an in-flight run on mount. The backend replays from event
  // index 0 so the caller rebuilds the same state the original requester saw.
  useEffect(() => {
    getActiveRun()
      .then((active) => {
        if (active) {
          onReattachRef.current?.(active);
          attachStream(active.stream_url);
        }
      })
      .catch((e) => console.error(e));

    return () => {
      esRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const start = async (
    dateIso: string,
    kind: "ingest" | "extract" | "full" = "full",
  ) => {
    try {
      const { stream_url } = await startRun(dateIso, kind);
      attachStream(stream_url);
    } catch (e) {
      setFinal(`Erro: ${String(e)}`);
      setRunning(false);
    }
  };

  return { running, stage, stageProgress, logs, final, start };
}
