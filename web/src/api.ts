export type DateEntry = {
  date: string;
  article_count: number;
  has_csv: boolean;
  has_dashboard: boolean;
  has_report: boolean;
};

export type NamedCount = { name: string; count: number };
export type SentimentBucket = { label: string; count: number };

export type Summary = {
  date: string;
  total: number;
  sentiment: SentimentBucket[];
  top_companies: NamedCount[];
  top_sites: NamedCount[];
  top_sectors: NamedCount[];
};

export type Health = {
  status: string;
  scheduler: string;
  next_run: string | null;
  db: string;
};

async function j<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${path}`);
  return r.json() as Promise<T>;
}

export const listDates = () => j<DateEntry[]>("/api/dates");
export const getSummary = (date: string) => j<Summary>(`/api/summary/${date}`);
export const getHealth = () => j<Health>("/api/health");
