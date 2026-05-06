import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Search, X } from "lucide-react";
import { getCompanies, getPortfolioSnapshot, getTrendsCompany } from "../../api";
import type {
  CompanyListItem,
  PortfolioSnapshotItem,
  WindowCompany,
  WindowSize,
} from "../../api";
import { usePortfolioStream } from "../../hooks/usePortfolioStream";
import { useAdvisor } from "../../hooks/useAdvisor";
import { ChartCard } from "../charts/ChartCard";
import { EmptyTile } from "../charts/_chart-axis";
import { SentimentVsPriceChart } from "../charts/SentimentVsPriceChart";
import {
  PortfolioPerformanceChart,
  type PerformanceSeries,
} from "../charts/PortfolioPerformanceChart";

const WINDOW_OPTIONS: WindowSize[] = [3, 7, 14];

// ── Financial jargon glossary ─────────────────────────────────────────────────

const JARGON: Record<string, string> = {
  volatilidade: "Medida de quanto o preço de uma ação oscila; alta volatilidade = grandes variações",
  correlação: "Grau em que dois ativos se movem juntos — correlação positiva significa que sobem e caem ao mesmo tempo",
  momentum: "Tendência de um ativo continuar na mesma direção de movimento recente",
  liquidez: "Facilidade de comprar ou vender uma ação sem impactar muito o preço",
  fundamentos: "Dados financeiros reais da empresa: lucro, receita, dívida, crescimento",
  valuation: "Estimativa do valor justo de uma empresa comparado ao seu preço atual",
  upside: "Potencial de valorização — quanto a ação pode subir",
  downside: "Risco de queda — quanto a ação pode perder de valor",
  beta: "Medida de risco relativo ao mercado: beta > 1 significa que a ação oscila mais que o índice",
  "dividend yield": "Percentual de dividendos pagos em relação ao preço da ação",
  "fluxo de caixa": "Dinheiro efetivamente entrando e saindo da empresa",
  "margem": "Percentual de lucro sobre a receita — indica eficiência operacional",
  oversold: "Ação considerada muito barata por indicadores técnicos, sugerindo possível recuperação",
  overbought: "Ação considerada cara por indicadores técnicos, sugerindo possível queda",
};

function annotate(text: string): React.ReactNode[] {
  const keys = Object.keys(JARGON).sort((a, b) => b.length - a.length);
  const pattern = new RegExp(`(${keys.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  const parts = text.split(pattern);
  return parts.map((part, i) => {
    const def = JARGON[part.toLowerCase()];
    if (def) {
      return (
        <abbr
          key={i}
          title={def}
          className="underline decoration-dotted decoration-primary/60 cursor-help text-primary/90"
        >
          {part}
        </abbr>
      );
    }
    return part;
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined, decimals = 2): string {
  if (n == null) return "—";
  return n.toFixed(decimals);
}

function formatMarketCap(v: number | null): string {
  if (v == null) return "—";
  if (v >= 1e12) return `R$ ${(v / 1e12).toFixed(1)}T`;
  if (v >= 1e9) return `R$ ${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `R$ ${(v / 1e6).toFixed(0)}M`;
  return `R$ ${v.toLocaleString("pt-BR")}`;
}

function loadQty(tickers: string[]): Record<string, number> {
  try {
    const raw = localStorage.getItem("portfolioQuantities");
    const stored = raw ? (JSON.parse(raw) as Record<string, number>) : {};
    return Object.fromEntries(tickers.map((t) => [t, stored[t] ?? 0]));
  } catch {
    return Object.fromEntries(tickers.map((t) => [t, 0]));
  }
}

function loadAvg(tickers: string[]): Record<string, number> {
  try {
    const raw = localStorage.getItem("portfolioAvgPrices");
    const stored = raw ? (JSON.parse(raw) as Record<string, number>) : {};
    return Object.fromEntries(tickers.map((t) => [t, stored[t] ?? 0]));
  } catch {
    return Object.fromEntries(tickers.map((t) => [t, 0]));
  }
}

function fmtBrl(n: number): string {
  return n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ── Stock cards ───────────────────────────────────────────────────────────────

const CARD_COLORS = [
  "hsl(186 100% 55%)",
  "hsl(320 100% 60%)",
  "hsl(60 100% 55%)",
  "hsl(160 100% 45%)",
  "hsl(280 100% 65%)",
];

function StockCards({
  portfolioTickers,
  snapshot,
  snapshotLoading,
  prices,
  flashMap,
  companies,
  quantities,
  onQtyChange,
  avgPrices,
  onAvgChange,
  windowSize,
}: {
  portfolioTickers: string[];
  snapshot: PortfolioSnapshotItem[];
  snapshotLoading: boolean;
  prices: Record<string, { currentClose: number | null; dayOpen: number | null; asOf: string | null }>;
  flashMap: Record<string, "up" | "down">;
  companies: CompanyListItem[];
  quantities: Record<string, number>;
  onQtyChange: (root: string, qty: number) => void;
  avgPrices: Record<string, number>;
  onAvgChange: (root: string, avg: number) => void;
  windowSize: WindowSize;
}) {
  const snapshotMap = useMemo(
    () => Object.fromEntries(snapshot.map((s) => [s.tickerRoot, s])),
    [snapshot]
  );

  return (
    <div className="flex gap-3 overflow-x-auto pb-1 w-full min-w-0">
      {portfolioTickers.map((root, idx) => {
        const snap = snapshotMap[root];
        const live = prices[root];
        const comp = companies.find((c) => c.tickerRoot === root);
        const currentClose = live?.currentClose ?? snap?.currentClose;
        const dayOpen = live?.dayOpen ?? snap?.dayOpen;
        const dayChangePct =
          currentClose != null && dayOpen != null && dayOpen !== 0
            ? ((currentClose - dayOpen) / dayOpen) * 100
            : null;
        const positive = dayChangePct != null && dayChangePct > 0;
        const negative = dayChangePct != null && dayChangePct < 0;
        const color = CARD_COLORS[idx % CARD_COLORS.length];

        return (
          <div
            key={root}
            className="w-48 shrink-0 rounded-lg border border-border bg-background/60 p-3 flex flex-col gap-2"
            style={{ borderTopColor: color, borderTopWidth: 2 }}
          >
            <div className="flex items-start justify-between gap-1">
              <span className="text-xs font-mono font-bold" style={{ color }}>
                {snap?.ticker ?? root}
              </span>
              {dayChangePct != null && (
                <span
                  className={`text-[10px] font-mono tabular-nums shrink-0 ${
                    positive ? "text-green-400" : negative ? "text-red-400" : "text-muted-foreground"
                  }`}
                >
                  {positive ? "▲" : negative ? "▼" : ""}{Math.abs(dayChangePct).toFixed(2)}%
                </span>
              )}
            </div>

            <div className="text-[10px] text-muted-foreground truncate leading-tight">
              {comp?.shortName ?? comp?.longName ?? root}
            </div>

            <div className="flex items-baseline gap-1.5">
              {snapshotLoading ? (
                <div className="h-4 w-14 bg-muted/30 rounded animate-pulse" />
              ) : (
                <span
                  key={`${root}-${currentClose}`}
                  className={`text-sm font-mono tabular-nums font-semibold ${
                    flashMap[root] === "up"
                      ? "price-flash-up"
                      : flashMap[root] === "down"
                        ? "price-flash-down"
                        : "text-foreground"
                  }`}
                >
                  {fmt(currentClose)}
                </span>
              )}
              {dayOpen != null && (
                <span className="text-[9px] text-muted-foreground/40 font-mono">
                  ab.{fmt(dayOpen)}
                </span>
              )}
            </div>

            <div className="flex items-center gap-2">
              {(["3", "7", "14"] as const).map((w) => {
                const val = snap?.changes?.[w];
                const isWindow = Number(w) === windowSize;
                return (
                  <span key={w} className={`flex flex-col items-center ${isWindow ? "opacity-100" : "opacity-40"}`}>
                    <span className="text-[8px] text-muted-foreground/60 font-mono">{w}d</span>
                    <span
                      className={`text-[10px] font-mono tabular-nums font-medium ${
                        val == null ? "text-muted-foreground/30"
                        : val > 0 ? "text-green-400"
                        : val < 0 ? "text-red-400"
                        : "text-muted-foreground"
                      }`}
                    >
                      {val == null ? "—" : `${val > 0 ? "+" : ""}${val.toFixed(1)}%`}
                    </span>
                  </span>
                );
              })}
            </div>

            <div className="pt-1 border-t border-border/40 space-y-1.5">
              <div className="flex items-center gap-1.5">
                <span className="text-[9px] font-mono text-muted-foreground/50 w-6 shrink-0">Qtd.</span>
                <input
                  type="number"
                  min={0}
                  value={quantities[root] || ""}
                  onChange={(e) => {
                    const v = parseInt(e.target.value, 10);
                    onQtyChange(root, isNaN(v) || v < 0 ? 0 : v);
                  }}
                  placeholder="0"
                  className="w-full bg-muted/20 border border-border/60 rounded px-1.5 py-0.5 text-[10px] font-mono text-right outline-none focus:border-primary/50 tabular-nums"
                />
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-[9px] font-mono text-muted-foreground/50 w-6 shrink-0">P.M.</span>
                <input
                  type="number"
                  min={0}
                  step={0.01}
                  value={avgPrices[root] || ""}
                  onChange={(e) => {
                    const v = parseFloat(e.target.value);
                    onAvgChange(root, isNaN(v) || v < 0 ? 0 : v);
                  }}
                  placeholder="0,00"
                  className="w-full bg-muted/20 border border-border/60 rounded px-1.5 py-0.5 text-[10px] font-mono text-right outline-none focus:border-primary/50 tabular-nums"
                />
              </div>
            </div>

            {(() => {
              const qty = quantities[root] ?? 0;
              const avg = avgPrices[root] ?? 0;
              if (qty <= 0 || avg <= 0 || currentClose == null) return null;
              const pnlPct = ((currentClose - avg) / avg) * 100;
              const pnlBrl = (currentClose - avg) * qty;
              const gain = pnlBrl >= 0;
              return (
                <div className={`text-[9px] font-mono tabular-nums text-right leading-tight ${gain ? "text-green-400" : "text-red-400"}`}>
                  {gain ? "+" : ""}R$ {fmtBrl(pnlBrl)}<br />
                  <span className="opacity-70">{gain ? "+" : ""}{pnlPct.toFixed(2)}% vs P.M.</span>
                </div>
              );
            })()}
          </div>
        );
      })}
    </div>
  );
}

// ── Portfolio summary (P&L vs average buy price) ─────────────────────────────

function PortfolioSummary({
  portfolioTickers,
  snapshot,
  prices,
  quantities,
  avgPrices,
  companies,
}: {
  portfolioTickers: string[];
  snapshot: PortfolioSnapshotItem[];
  prices: Record<string, { currentClose: number | null; dayOpen: number | null; asOf: string | null }>;
  quantities: Record<string, number>;
  avgPrices: Record<string, number>;
  companies: CompanyListItem[];
}) {
  const snapshotMap = useMemo(
    () => Object.fromEntries(snapshot.map((s) => [s.tickerRoot, s])),
    [snapshot]
  );

  const rows = portfolioTickers
    .map((root, idx) => {
      const qty = quantities[root] ?? 0;
      const avg = avgPrices[root] ?? 0;
      const live = prices[root];
      const snap = snapshotMap[root];
      const currentClose = live?.currentClose ?? snap?.currentClose ?? null;
      const comp = companies.find((c) => c.tickerRoot === root);
      const ticker = snap?.ticker ?? root;
      const name = comp?.shortName ?? comp?.longName ?? root;
      const invested = qty > 0 && avg > 0 ? qty * avg : null;
      const current = qty > 0 && currentClose != null ? qty * currentClose : null;
      const pnlBrl = invested != null && current != null ? current - invested : null;
      const pnlPct = invested != null && pnlBrl != null ? (pnlBrl / invested) * 100 : null;
      return { root, ticker, name, qty, avg, currentClose, invested, current, pnlBrl, pnlPct, color: CARD_COLORS[idx % CARD_COLORS.length] };
    })
    .filter((r) => r.qty > 0 || r.avg > 0);

  if (rows.length === 0) return null;

  const totalInvested = rows.reduce((s, r) => s + (r.invested ?? 0), 0);
  const totalCurrent = rows.reduce((s, r) => s + (r.current ?? 0), 0);
  const totalPnlBrl = totalInvested > 0 && totalCurrent > 0 ? totalCurrent - totalInvested : null;
  const totalPnlPct = totalInvested > 0 && totalPnlBrl != null ? (totalPnlBrl / totalInvested) * 100 : null;

  const th = "px-3 py-2 text-left text-[10px] font-mono uppercase tracking-widest text-muted-foreground/60 whitespace-nowrap";
  const td = "px-3 py-2 text-xs font-mono tabular-nums whitespace-nowrap";

  return (
    <div className="rounded-lg border border-border bg-background/60 overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-4 flex-wrap">
        <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70">
          Resumo da carteira
        </span>
        {totalPnlBrl != null && (
          <div className="flex items-center gap-4">
            <span className="text-[10px] font-mono text-muted-foreground/50">
              Investido: <span className="text-foreground">R$ {fmtBrl(totalInvested)}</span>
            </span>
            <span className="text-[10px] font-mono text-muted-foreground/50">
              Atual: <span className="text-foreground">R$ {fmtBrl(totalCurrent)}</span>
            </span>
            <span className={`text-sm font-mono font-semibold ${totalPnlBrl >= 0 ? "text-green-400" : "text-red-400"}`}>
              {totalPnlBrl >= 0 ? "+" : ""}R$ {fmtBrl(totalPnlBrl)}
              {totalPnlPct != null && (
                <span className="ml-1.5 text-[11px] font-normal opacity-80">
                  ({totalPnlPct >= 0 ? "+" : ""}{totalPnlPct.toFixed(2)}%)
                </span>
              )}
            </span>
          </div>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="border-b border-border">
            <tr>
              <th className={th}>Ativo</th>
              <th className={`${th} text-right`}>Qtd.</th>
              <th className={`${th} text-right`}>P.M.</th>
              <th className={`${th} text-right`}>Atual</th>
              <th className={`${th} text-right`}>Resultado R$</th>
              <th className={`${th} text-right`}>Resultado %</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.root} className="border-b border-border/40">
                <td className={td}>
                  <span className="font-semibold" style={{ color: r.color }}>{r.ticker}</span>
                  <span className="ml-1.5 text-muted-foreground/60 text-[10px]">{r.name}</span>
                </td>
                <td className={`${td} text-right text-muted-foreground`}>{r.qty || "—"}</td>
                <td className={`${td} text-right text-muted-foreground`}>
                  {r.avg > 0 ? `R$ ${fmtBrl(r.avg)}` : "—"}
                </td>
                <td className={`${td} text-right`}>
                  {r.currentClose != null ? `R$ ${fmtBrl(r.currentClose)}` : "—"}
                </td>
                <td className={`${td} text-right ${r.pnlBrl == null ? "text-muted-foreground/40" : r.pnlBrl >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {r.pnlBrl == null ? "—" : `${r.pnlBrl >= 0 ? "+" : ""}R$ ${fmtBrl(r.pnlBrl)}`}
                </td>
                <td className={`${td} text-right ${r.pnlPct == null ? "text-muted-foreground/40" : r.pnlPct >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {r.pnlPct == null ? "—" : `${r.pnlPct >= 0 ? "+" : ""}${r.pnlPct.toFixed(2)}%`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Portfolio performance chart ───────────────────────────────────────────────

function PortfolioPerformance({
  portfolioTickers,
  windowSize,
  quantities,
}: {
  portfolioTickers: string[];
  windowSize: WindowSize;
  quantities: Record<string, number>;
}) {
  const [companyData, setCompanyData] = useState<Record<string, WindowCompany>>({});
  const [loading, setLoading] = useState(false);

  const tickersKey = portfolioTickers.join(",");

  useEffect(() => {
    if (portfolioTickers.length === 0) { setCompanyData({}); return; }
    const ctrl = new AbortController();
    setLoading(true);
    Promise.all(
      portfolioTickers.map((t) =>
        getTrendsCompany(t, windowSize, undefined, ctrl.signal).then((d) => ({ t, d }))
      )
    )
      .then((results) => {
        if (ctrl.signal.aborted) return;
        setCompanyData(Object.fromEntries(results.map(({ t, d }) => [t, d])));
      })
      .catch(() => {})
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
  }, [tickersKey, windowSize]); // eslint-disable-line react-hooks/exhaustive-deps

  const series: PerformanceSeries[] = useMemo(
    () =>
      portfolioTickers
        .map((t, i) => {
          const d = companyData[t];
          if (!d) return null;
          return {
            ticker: t,
            color: CARD_COLORS[i % CARD_COLORS.length],
            points: d.daily.map((row) => ({ date: row.date, close: row.close })),
          };
        })
        .filter((s): s is PerformanceSeries => s !== null),
    [companyData, portfolioTickers]
  );

  if (loading) {
    return <div className="h-[220px] bg-muted/20 rounded animate-pulse" />;
  }

  if (series.length === 0) return null;

  return (
    <PortfolioPerformanceChart series={series} quantities={quantities} mode="pct" />
  );
}

// ── Per-company sentiment × price charts ──────────────────────────────────────

function CompanyChart({
  ticker,
  windowSize,
}: {
  ticker: string;
  windowSize: WindowSize;
}) {
  const [data, setData] = useState<WindowCompany | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setData(null);
    getTrendsCompany(ticker, windowSize, undefined, ctrl.signal)
      .then((d) => { if (!ctrl.signal.aborted) { setData(d); setLoading(false); } })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        setError(e instanceof Error ? e : new Error(String(e)));
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [ticker, windowSize]);

  const corrLabel =
    data?.correlation == null ? undefined
    : `r = ${data.correlation >= 0 ? "+" : ""}${data.correlation.toFixed(2)}`;

  return (
    <ChartCard title={ticker} subtitle={corrLabel}>
      {loading ? (
        <div className="h-48 bg-muted/20 rounded animate-pulse" />
      ) : error ? (
        <EmptyTile label="sem dados" />
      ) : data ? (
        <SentimentVsPriceChart data={{ points: data.daily }} />
      ) : (
        <EmptyTile />
      )}
    </ChartCard>
  );
}

// ── Advisor summary ───────────────────────────────────────────────────────────

function AdvisorSummary({
  portfolioTickers,
  windowSize,
}: {
  portfolioTickers: string[];
  windowSize: WindowSize;
}) {
  const advisor = useAdvisor("overall", windowSize, undefined, portfolioTickers);
  const { data, loading, unavailable, error } = advisor;

  return (
    <ChartCard
      title="Análise de IA · Assessor de carteira"
      subtitle={
        data?.model
          ? `${data.model} · ${windowSize}d · ${data.generatedAt ? new Date(data.generatedAt).toLocaleString("pt-BR") : "gerado agora"}`
          : `gerado por IA com base nas notícias dos últimos ${windowSize} dias`
      }
    >
      {loading ? (
        <div className="space-y-3 animate-pulse">
          {[1, 0.92, 0.75, null, 0.88, 0.66].map((w, i) =>
            w == null ? <div key={i} className="h-2" /> : (
              <div key={i} className="h-3 bg-muted/30 rounded" style={{ width: `${w * 100}%` }} />
            )
          )}
        </div>
      ) : unavailable ? (
        <EmptyTile label="análise temporariamente indisponível" />
      ) : error ? (
        <EmptyTile label={`erro: ${error.message}`} />
      ) : data ? (
        <div className="space-y-4 text-sm font-mono leading-relaxed text-foreground/90">
          {data.paragraphs.map((p, i) => (
            <p key={i}>{annotate(p)}</p>
          ))}
          <p className="text-[10px] text-muted-foreground/40 pt-1">
            Termos sublinhados têm explicações — passe o mouse para ver.
          </p>
        </div>
      ) : (
        <EmptyTile />
      )}
    </ChartCard>
  );
}

// ── Company selection table ───────────────────────────────────────────────────

function CompanyTable({
  companies,
  companiesLoading,
  portfolioTickers,
  onToggle,
}: {
  companies: CompanyListItem[];
  companiesLoading: boolean;
  portfolioTickers: string[];
  onToggle: (root: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    if (!search.trim()) return companies;
    const q = search.toLowerCase();
    return companies.filter(
      (c) =>
        c.tickerRoot.toLowerCase().includes(q) ||
        c.ticker.toLowerCase().includes(q) ||
        (c.shortName ?? "").toLowerCase().includes(q) ||
        (c.longName ?? "").toLowerCase().includes(q)
    );
  }, [companies, search]);

  const th = "px-4 py-2 text-left text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70 whitespace-nowrap";
  const td = "px-4 py-2 text-xs font-mono whitespace-nowrap";

  return (
    <div className="rounded-lg border border-border bg-background/60 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-muted/20 transition-colors"
      >
        <span className="text-xs font-mono uppercase tracking-widest text-muted-foreground/70">
          Selecionar empresas
          {portfolioTickers.length > 0 && (
            <span className="ml-2 text-primary/70">
              {portfolioTickers.length} selecionada{portfolioTickers.length > 1 ? "s" : ""}
            </span>
          )}
        </span>
        <ChevronDown
          className={`h-3.5 w-3.5 text-muted-foreground/50 transition-transform ${open ? "rotate-0" : "-rotate-90"}`}
        />
      </button>

      {open && (
        <>
          <div className="px-4 py-2 border-t border-border flex items-center justify-end">
            <div className="relative flex items-center">
              <Search className="absolute left-2.5 h-3.5 w-3.5 text-muted-foreground/50" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar…"
                className="pl-8 pr-8 py-1.5 text-xs font-mono bg-muted/30 border border-border rounded-md outline-none focus:border-primary/50 w-48"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  className="absolute right-2 text-muted-foreground/50 hover:text-foreground"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
          <div className="max-h-72 overflow-y-auto border-t border-border">
            {companiesLoading ? (
              <div className="px-4 py-8 text-center text-xs font-mono text-muted-foreground animate-pulse">
                carregando…
              </div>
            ) : (
              <table className="w-full">
                <thead className="sticky top-0 bg-background/90 backdrop-blur-sm border-b border-border">
                  <tr>
                    <th className={th}>Ticker</th>
                    <th className={th}>Nome</th>
                    <th className={th}>Setor</th>
                    <th className={`${th} text-right`}>Market Cap</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((c) => {
                    const selected = portfolioTickers.includes(c.tickerRoot);
                    return (
                      <tr
                        key={c.tickerRoot}
                        onClick={() => onToggle(c.tickerRoot)}
                        className={`cursor-pointer border-b border-border/40 transition-colors ${
                          selected ? "bg-primary/10 border-l-2 border-l-primary" : "hover:bg-muted/30"
                        }`}
                      >
                        <td className={`${td} text-primary font-semibold`}>{c.ticker}</td>
                        <td className={`${td} text-foreground`}>
                          {c.shortName ?? c.longName ?? c.tickerRoot}
                        </td>
                        <td className={`${td} text-muted-foreground`}>{c.sector ?? "—"}</td>
                        <td className={`${td} text-right text-muted-foreground`}>
                          {formatMarketCap(c.marketCap)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ── Root ──────────────────────────────────────────────────────────────────────

export function PortfolioView({
  portfolioTickers,
  onPortfolioChange,
}: {
  portfolioTickers: string[];
  onPortfolioChange: (tickers: string[]) => void;
}) {
  const [windowSize, setWindowSize] = useState<WindowSize>(7);
  const [quantities, setQuantitiesRaw] = useState<Record<string, number>>(
    () => loadQty(portfolioTickers)
  );
  const [avgPrices, setAvgPricesRaw] = useState<Record<string, number>>(
    () => loadAvg(portfolioTickers)
  );

  useEffect(() => {
    setQuantitiesRaw(loadQty(portfolioTickers));
    setAvgPricesRaw(loadAvg(portfolioTickers));
  }, [portfolioTickers.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  const setQty = (root: string, qty: number) => {
    setQuantitiesRaw((prev) => {
      const next = { ...prev, [root]: qty };
      try {
        const stored = JSON.parse(localStorage.getItem("portfolioQuantities") ?? "{}") as Record<string, number>;
        localStorage.setItem("portfolioQuantities", JSON.stringify({ ...stored, [root]: qty }));
      } catch {}
      return next;
    });
  };

  const setAvg = (root: string, avg: number) => {
    setAvgPricesRaw((prev) => {
      const next = { ...prev, [root]: avg };
      try {
        const stored = JSON.parse(localStorage.getItem("portfolioAvgPrices") ?? "{}") as Record<string, number>;
        localStorage.setItem("portfolioAvgPrices", JSON.stringify({ ...stored, [root]: avg }));
      } catch {}
      return next;
    });
  };

  const [companies, setCompanies] = useState<CompanyListItem[]>([]);
  const [companiesLoading, setCompaniesLoading] = useState(true);
  const [snapshot, setSnapshot] = useState<PortfolioSnapshotItem[]>([]);
  const [snapshotLoading, setSnapshotLoading] = useState(false);

  const { prices, connected } = usePortfolioStream(portfolioTickers);

  const prevPricesRef = useRef<Record<string, number | null>>({});
  const [flashMap, setFlashMap] = useState<Record<string, "up" | "down">>({});

  useEffect(() => {
    const newFlash: Record<string, "up" | "down"> = {};
    let changed = false;
    for (const [root, item] of Object.entries(prices)) {
      const prev = prevPricesRef.current[root];
      const curr = item.currentClose;
      if (prev !== undefined && curr !== null && prev !== null && prev !== curr) {
        newFlash[root] = curr > prev ? "up" : "down";
        changed = true;
      }
      prevPricesRef.current[root] = curr;
    }
    if (!changed) return;
    setFlashMap(newFlash);
    const t = setTimeout(() => setFlashMap({}), 700);
    return () => clearTimeout(t);
  }, [prices]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const ctrl = new AbortController();
    setCompaniesLoading(true);
    getCompanies(ctrl.signal)
      .then(setCompanies)
      .catch(() => {})
      .finally(() => setCompaniesLoading(false));
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    if (portfolioTickers.length === 0) { setSnapshot([]); return; }
    const ctrl = new AbortController();
    setSnapshotLoading(true);
    getPortfolioSnapshot(portfolioTickers, [3, 7, 14], ctrl.signal)
      .then(setSnapshot)
      .catch(() => {})
      .finally(() => setSnapshotLoading(false));
    return () => ctrl.abort();
  }, [portfolioTickers.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (root: string) => {
    if (portfolioTickers.includes(root)) {
      onPortfolioChange(portfolioTickers.filter((t) => t !== root));
    } else {
      onPortfolioChange([...portfolioTickers, root]);
    }
  };

  const hasAnyQty = portfolioTickers.some((t) => (quantities[t] ?? 0) > 0);

  return (
    <div className="space-y-6 w-full min-w-0">
      {/* Header */}
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h2 className="font-mono uppercase tracking-[0.25em] text-xs text-muted-foreground mb-1">
            Carteira
          </h2>
          <p className="text-2xl font-semibold font-mono">
            {portfolioTickers.length === 0
              ? "Sem empresas selecionadas"
              : `${portfolioTickers.length} empresa${portfolioTickers.length > 1 ? "s" : ""}`}
          </p>
        </div>

        <div className="flex items-center gap-4">
          {portfolioTickers.length > 0 && (
            <div className="flex items-center gap-2 text-[10px] font-mono text-muted-foreground/60">
              {connected ? (
                <span className="relative flex h-2 w-2">
                  <span
                    className="absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"
                    style={{ animation: "live-ring 1.5s ease-out infinite" }}
                  />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-green-400 shadow-[0_0_6px_theme(colors.green.400)]" />
                </span>
              ) : (
                <span className="h-2 w-2 rounded-full bg-muted-foreground/40" />
              )}
              {connected ? "ao vivo" : "conectando…"}
            </div>
          )}

          {portfolioTickers.length > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70">
                Janela
              </span>
              <div className="inline-flex border border-border rounded-md p-0.5 bg-muted/30">
                {WINDOW_OPTIONS.map((n) => {
                  const isActive = n === windowSize;
                  return (
                    <button
                      key={n}
                      type="button"
                      onClick={() => setWindowSize(n)}
                      className={`px-3 py-1.5 text-xs font-mono uppercase tracking-widest rounded-sm transition-all ${
                        isActive
                          ? "bg-primary/15 text-primary border neon-edge"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {n}d
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Stock cards — fixed width, no grow */}
      {portfolioTickers.length > 0 && (
        <StockCards
          portfolioTickers={portfolioTickers}
          snapshot={snapshot}
          snapshotLoading={snapshotLoading}
          prices={prices}
          flashMap={flashMap}
          companies={companies}
          quantities={quantities}
          onQtyChange={setQty}
          avgPrices={avgPrices}
          onAvgChange={setAvg}
          windowSize={windowSize}
        />
      )}

      {/* Portfolio P&L summary — shown when qty or avg price is set */}
      {portfolioTickers.length > 0 && (
        <PortfolioSummary
          portfolioTickers={portfolioTickers}
          snapshot={snapshot}
          prices={prices}
          quantities={quantities}
          avgPrices={avgPrices}
          companies={companies}
        />
      )}

      {/* AI advisor summary — right after cards */}
      {portfolioTickers.length > 0 && (
        <AdvisorSummary portfolioTickers={portfolioTickers} windowSize={windowSize} />
      )}

      {/* Portfolio performance chart */}
      {portfolioTickers.length > 0 && (
        <ChartCard
          title="Evolução da carteira"
          subtitle={hasAnyQty ? "% de variação por empresa · carteira ponderada (tracejado)" : "% de variação por empresa"}
        >
          <PortfolioPerformance
            portfolioTickers={portfolioTickers}
            windowSize={windowSize}
            quantities={quantities}
          />
        </ChartCard>
      )}

      {/* Per-company sentiment × price charts */}
      {portfolioTickers.length > 0 && (
        <div>
          <p className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70 mb-3">
            Sentimento × Cotação
          </p>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {portfolioTickers.map((ticker) => (
              <CompanyChart key={ticker} ticker={ticker} windowSize={windowSize} />
            ))}
          </div>
        </div>
      )}

      {/* Collapsible company selector */}
      <CompanyTable
        companies={companies}
        companiesLoading={companiesLoading}
        portfolioTickers={portfolioTickers}
        onToggle={toggle}
      />
    </div>
  );
}
