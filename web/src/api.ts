export type DatesPayload = {
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
      stage: "ingest" | "extract" | "summarize" | string;
      current: number;
      total: number;
    }
  | { type: "done"; n_fetched: number; n_extracted: number }
  | { type: "error"; message: string };

export type ReportPayload = {
  date: string;
  counts: {
    total: number;
    publishers: number;
    bySentiment: { positive: number; neutral: number; negative: number };
  };
  topCompanies: Array<{
    name: string;
    positive: number;
    neutral: number;
    negative: number;
    total: number;
    tilt: number;
  }>;
  sentimentByPublisher: Array<{
    site: string;
    positive: number;
    neutral: number;
    negative: number;
    total: number;
  }>;
  sectorMatrix: Array<{
    sector: string;
    positive: number;
    neutral: number;
    negative: number;
    tilt: number;
    topCompanies: string[];
  }>;
  hourly: Array<{
    hour: number;
    positive: number;
    neutral: number;
    negative: number;
  }>;
  topSubjects: Array<{ subject: string; count: number }>;
  topTickers: Array<{ ticker: string; count: number }>;
  scoreHistogram: Array<{ bucketStart: number; bucketEnd: number; count: number }>;
  currencies: Array<{ currency: string; count: number }>;
};

export async function getReport(
  date: string,
  signal?: AbortSignal,
): Promise<ReportPayload | null> {
  const r = await fetch(`/api/reports/${encodeURIComponent(date)}`, { signal });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`GET /api/reports/${date} → ${r.status}`);
  return r.json();
}

export type CompanySummary = {
  ticker: string;
  name: string | null;
  date: string;
  good: string[];
  bad: string[];
  articleCount: number;
  model: string;
  articles: Array<{
    url: string;
    title: string | null;
    site: string | null;
    sentiment: string | null;
    sentimentScore: number | null;
  }>;
};

export type StockOhlc = {
  ticker: string;
  selectedDate: string;
  bars: Array<{
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number | null;
  }>;
};

export type SentimentSeries = {
  ticker: string;
  selectedDate: string;
  points: Array<{
    date: string;
    close: number;
    positive: number;
    neutral: number;
    negative: number;
    total: number;
    net: number;
    avgScore: number | null;
  }>;
  correlation: number | null;
};

export async function getSentimentSeries(
  ticker: string,
  date: string,
  signal?: AbortSignal,
): Promise<SentimentSeries> {
  const r = await fetch(
    `/api/companies/${encodeURIComponent(ticker)}/sentiment-series/${encodeURIComponent(date)}`,
    { signal },
  );
  if (!r.ok)
    throw new Error(`GET /api/companies/${ticker}/sentiment-series/${date} → ${r.status}`);
  return r.json();
}

export async function getCompanySummary(
  ticker: string,
  date: string,
  signal?: AbortSignal,
): Promise<CompanySummary | null> {
  const r = await fetch(
    `/api/companies/${encodeURIComponent(ticker)}/summary/${encodeURIComponent(date)}`,
    { signal },
  );
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`GET /api/companies/${ticker}/summary/${date} → ${r.status}`);
  return r.json();
}

export async function getStockOhlc(
  ticker: string,
  date: string,
  signal?: AbortSignal,
): Promise<StockOhlc> {
  const r = await fetch(
    `/api/stocks/${encodeURIComponent(ticker)}/ohlc/${encodeURIComponent(date)}`,
    { signal },
  );
  if (!r.ok) throw new Error(`GET /api/stocks/${ticker}/ohlc/${date} → ${r.status}`);
  return r.json();
}

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
