import { useEffect, useState } from "react";
import {
  DateEntry,
  Health,
  Summary,
  getHealth,
  getSummary,
  listDates,
} from "./api";

export default function App() {
  const [dates, setDates] = useState<DateEntry[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listDates()
      .then((d) => {
        setDates(d);
        if (d.length > 0) setSelected(d[0].date);
      })
      .catch((e) => setError(String(e)));
    getHealth().then(setHealth).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selected) return;
    setSummary(null);
    getSummary(selected).then(setSummary).catch((e) => setError(String(e)));
  }, [selected]);

  const entry = dates.find((d) => d.date === selected);

  return (
    <main>
      <h1>Finance News — pipeline viewer</h1>
      <p className="muted">
        Backend: {health?.status ?? "…"} · scheduler:{" "}
        {health?.scheduler ?? "…"} · next run:{" "}
        {health?.next_run ?? "—"}
      </p>

      <div className="controls">
        <label>
          Data:{" "}
          <select
            value={selected ?? ""}
            onChange={(e) => setSelected(e.target.value)}
          >
            {dates.map((d) => (
              <option key={d.date} value={d.date}>
                {d.date} ({d.article_count})
              </option>
            ))}
          </select>
        </label>
        {entry?.has_csv && selected && (
          <a className="download" href={`/api/files/${selected}/csv`}>
            Baixar CSV
          </a>
        )}
        {entry?.has_report && selected && (
          <a
            className="download"
            href={`/api/files/${selected}/report`}
            target="_blank"
            rel="noreferrer"
          >
            Abrir relatório
          </a>
        )}
      </div>

      {error && <p style={{ color: "tomato" }}>{error}</p>}

      {entry?.has_dashboard && selected && (
        <img
          className="artifact"
          src={`/api/files/${selected}/dashboard`}
          alt={`Dashboard ${selected}`}
        />
      )}

      {summary && (
        <div className="summary">
          <section>
            <h2>Sentimento</h2>
            <ul>
              {summary.sentiment.map((s) => (
                <li key={s.label}>
                  <span>{s.label}</span>
                  <span>{s.count}</span>
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h2>Top empresas</h2>
            <ul>
              {summary.top_companies.map((c) => (
                <li key={c.name}>
                  <span>{c.name}</span>
                  <span>{c.count}</span>
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h2>Top veículos</h2>
            <ul>
              {summary.top_sites.map((c) => (
                <li key={c.name}>
                  <span>{c.name}</span>
                  <span>{c.count}</span>
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h2>Top setores</h2>
            <ul>
              {summary.top_sectors.map((c) => (
                <li key={c.name}>
                  <span>{c.name}</span>
                  <span>{c.count}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </main>
  );
}
