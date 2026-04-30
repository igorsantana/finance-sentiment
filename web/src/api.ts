export type DatesPayload = {
  processed: string[];
  with_articles: string[];
};

export type StreamEvent =
  | {
      type: "log";
      level: string;
      logger: string;
      ts: number;
      message: string;
    }
  | {
      type: "progress";
      stage: "ingest" | "extract" | "render" | string;
      current: number;
      total: number;
    }
  | { type: "done"; n_fetched: number; n_extracted: number }
  | { type: "error"; message: string };

export async function getDates(): Promise<DatesPayload> {
  const r = await fetch("/api/dates");
  if (!r.ok) throw new Error(`GET /api/dates → ${r.status}`);
  return r.json();
}

export type ActiveRun = {
  run_id: string;
  target_date: string;
  kind: string;
  stream_url: string;
};

export async function getActiveRun(): Promise<ActiveRun | null> {
  const r = await fetch("/api/runs/active");
  if (!r.ok) throw new Error(`GET /api/runs/active → ${r.status}`);
  return r.json();
}

export async function startRun(
  date: string,
  kind: "ingest" | "extract" | "full" = "full",
): Promise<{ run_id: string; stream_url: string }> {
  const r = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date, kind }),
  });
  if (!r.ok) throw new Error(`POST /api/runs → ${r.status}`);
  return r.json();
}

export function openStream(
  streamUrl: string,
  onEvent: (ev: StreamEvent) => void,
  onClose?: () => void,
): EventSource {
  const es = new EventSource(streamUrl);
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data) as StreamEvent);
    } catch (err) {
      console.warn("bad SSE payload", err, e.data);
    }
  };
  // Important: do NOT close the EventSource on every `error` event. The
  // browser fires `error` on transient drops (and then auto-reconnects on
  // its own); closing here would kill the session after the first blip.
  // We only treat it as terminal once the connection is truly closed.
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) {
      onClose?.();
    }
  };
  return es;
}

export function toIsoDate(d: Date): string {
  // Convert to São Paulo timezone (where articles and runs are stored).
  const spFormatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return spFormatter.format(d);
}
