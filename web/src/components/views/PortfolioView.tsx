import { useEffect, useMemo, useRef, useState } from "react";
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
  avgPrices,
  windowSize,
}: {
  portfolioTickers: string[];
  snapshot: PortfolioSnapshotItem[];
  snapshotLoading: boolean;
  prices: Record<string, { currentClose: number | null; dayOpen: number | null; asOf: string | null }>;
  flashMap: Record<string, "up" | "down">;
  companies: CompanyListItem[];
  quantities: Record<string, number>;
  avgPrices: Record<string, number>;
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
        const qty = quantities[root] ?? 0;
        const avg = avgPrices[root] ?? 0;
        const pnlPct = qty > 0 && avg > 0 && currentClose != null ? ((currentClose - avg) / avg) * 100 : null;
        const pnlBrl = qty > 0 && avg > 0 && currentClose != null ? (currentClose - avg) * qty : null;
        const gain = pnlBrl != null && pnlBrl >= 0;

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

            {pnlBrl != null && (
              <div className={`text-[9px] font-mono tabular-nums text-right leading-tight pt-1 border-t border-border/40 ${gain ? "text-green-400" : "text-red-400"}`}>
                {gain ? "+" : ""}R$ {fmtBrl(pnlBrl)}<br />
                <span className="opacity-70">{gain ? "+" : ""}{pnlPct!.toFixed(2)}% vs P.M.</span>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Portfolio summary ─────────────────────────────────────────────────────────

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
      const dayOpen = live?.dayOpen ?? snap?.dayOpen ?? null;
      const comp = companies.find((c) => c.tickerRoot === root);
      const ticker = snap?.ticker ?? root;
      const name = comp?.shortName ?? comp?.longName ?? root;
      const invested = qty > 0 && avg > 0 ? qty * avg : null;
      const current = qty > 0 && currentClose != null ? qty * currentClose : null;
      const pnlBrl = invested != null && current != null ? current - invested : null;
      const pnlPct = invested != null && pnlBrl != null ? (pnlBrl / invested) * 100 : null;
      const dayChangeBrl =
        qty > 0 && currentClose != null && dayOpen != null && dayOpen !== 0
          ? (currentClose - dayOpen) * qty
          : null;
      return {
        root, ticker, name, qty, avg, currentClose, dayOpen,
        invested, current, pnlBrl, pnlPct, dayChangeBrl,
        color: CARD_COLORS[idx % CARD_COLORS.length],
      };
    })
    .filter((r) => r.qty > 0 || r.avg > 0);

  if (rows.length === 0) return null;

  const totalInvested = rows.reduce((s, r) => s + (r.invested ?? 0), 0);
  const totalCurrent = rows.reduce((s, r) => s + (r.current ?? 0), 0);
  const totalPnlBrl = totalInvested > 0 && totalCurrent > 0 ? totalCurrent - totalInvested : null;
  const totalPnlPct = totalInvested > 0 && totalPnlBrl != null ? (totalPnlBrl / totalInvested) * 100 : null;
  const totalDayChange = rows.reduce((s, r) => s + (r.dayChangeBrl ?? 0), 0);
  const hasDayChange = rows.some((r) => r.dayChangeBrl != null);

  const th = "px-3 py-2 text-left text-[10px] font-mono uppercase tracking-widest text-muted-foreground/60 whitespace-nowrap";
  const td = "px-3 py-2 text-xs font-mono tabular-nums whitespace-nowrap";

  return (
    <div className="rounded-lg border border-border bg-background/60 overflow-hidden">
      {/* Hero section */}
      <div className="px-6 py-5 border-b border-border bg-muted/5">
        <p className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/60 mb-2">
          Resumo da carteira
        </p>

        <div className="flex items-end gap-4 flex-wrap">
          {totalCurrent > 0 ? (
            <div>
              <p className="text-[10px] font-mono text-muted-foreground/50 mb-0.5">Patrimônio atual</p>
              <p className="text-3xl font-mono font-bold tabular-nums text-foreground">
                R$ {fmtBrl(totalCurrent)}
              </p>
            </div>
          ) : (
            <div>
              <p className="text-[10px] font-mono text-muted-foreground/50 mb-0.5">Investido</p>
              <p className="text-3xl font-mono font-bold tabular-nums text-foreground">
                R$ {fmtBrl(totalInvested)}
              </p>
            </div>
          )}

          {totalPnlBrl != null && (
            <div className="pb-0.5">
              <p className="text-[10px] font-mono text-muted-foreground/50 mb-0.5">Resultado total</p>
              <p className={`text-lg font-mono font-semibold tabular-nums ${totalPnlBrl >= 0 ? "text-green-400" : "text-red-400"}`}>
                {totalPnlBrl >= 0 ? "+" : ""}R$ {fmtBrl(totalPnlBrl)}
                {totalPnlPct != null && (
                  <span className="ml-1.5 text-sm font-normal opacity-80">
                    ({totalPnlPct >= 0 ? "+" : ""}{totalPnlPct.toFixed(2)}%)
                  </span>
                )}
              </p>
            </div>
          )}
        </div>

        {/* Secondary stats row */}
        <div className="flex gap-6 mt-3 flex-wrap">
          {totalInvested > 0 && totalCurrent > 0 && (
            <div className="text-[11px] font-mono text-muted-foreground/60">
              Custo médio: <span className="text-foreground">R$ {fmtBrl(totalInvested)}</span>
            </div>
          )}
          {hasDayChange && (
            <div className="text-[11px] font-mono text-muted-foreground/60">
              Variação do dia:{" "}
              <span className={totalDayChange >= 0 ? "text-green-400" : "text-red-400"}>
                {totalDayChange >= 0 ? "+" : ""}R$ {fmtBrl(totalDayChange)}
              </span>
            </div>
          )}
          <div className="text-[11px] font-mono text-muted-foreground/60">
            {rows.length} ativo{rows.length > 1 ? "s" : ""}
          </div>
        </div>
      </div>

      {/* Breakdown table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="border-b border-border bg-muted/5">
            <tr>
              <th className={th}>Ativo</th>
              <th className={`${th} text-right`}>Qtd.</th>
              <th className={`${th} text-right`}>P.M.</th>
              <th className={`${th} text-right`}>Atual</th>
              <th className={`${th} text-right`}>Resultado R$</th>
              <th className={`${th} text-right`}>Resultado %</th>
              <th className={`${th} text-right`}>Alocação</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const alloc = totalCurrent > 0 && r.current != null ? (r.current / totalCurrent) * 100 : null;
              return (
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
                  <td className={`${td} text-right text-muted-foreground/70`}>
                    {alloc != null ? `${alloc.toFixed(1)}%` : "—"}
                  </td>
                </tr>
              );
            })}
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

// ── Root ──────────────────────────────────────────────────────────────────────

export function PortfolioView({
  portfolioTickers,
  quantities,
  avgPrices,
}: {
  portfolioTickers: string[];
  quantities: Record<string, number>;
  avgPrices: Record<string, number>;
}) {
  const [windowSize, setWindowSize] = useState<WindowSize>(7);

  const [companies, setCompanies] = useState<CompanyListItem[]>([]);
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
    getCompanies(ctrl.signal)
      .then(setCompanies)
      .catch(() => {});
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

      {portfolioTickers.length === 0 && (
        <p className="text-sm font-mono text-muted-foreground/60">
          Configure sua carteira em <span className="text-primary">Admin → Carteira</span>.
        </p>
      )}

      {portfolioTickers.length > 0 && (
        <StockCards
          portfolioTickers={portfolioTickers}
          snapshot={snapshot}
          snapshotLoading={snapshotLoading}
          prices={prices}
          flashMap={flashMap}
          companies={companies}
          quantities={quantities}
          avgPrices={avgPrices}
          windowSize={windowSize}
        />
      )}

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

      {portfolioTickers.length > 0 && (
        <AdvisorSummary portfolioTickers={portfolioTickers} windowSize={windowSize} />
      )}

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
    </div>
  );
}
