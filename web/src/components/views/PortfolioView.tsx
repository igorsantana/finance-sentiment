import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Search, X } from "lucide-react";
import { getCompanies, getPortfolioSnapshot } from "../../api";
import type { CompanyListItem, PortfolioSnapshotItem, WindowSize } from "../../api";
import { usePortfolioStream } from "../../hooks/usePortfolioStream";
import { useTrendsOverall } from "../../hooks/useTrendsOverall";
import { useAdvisor } from "../../hooks/useAdvisor";
import { ChartCard } from "../charts/ChartCard";
import { EmptyTile } from "../charts/_chart-axis";
import { WindowSentimentLine } from "../charts/WindowSentimentLine";
import { WindowVolumeBars } from "../charts/WindowVolumeBars";
import { SectorHeatmap } from "../charts/SectorHeatmap";
import { SentimentByPublisher } from "../charts/SentimentByPublisher";
import { TopTickers } from "../charts/TopTickers";
import { TopSubjects } from "../charts/TopSubjects";

const WINDOW_OPTIONS: WindowSize[] = [3, 7, 14];

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

// ── Stock summary strip ────────────────────────────────────────────────────────

function StockStrip({
  portfolioTickers,
  snapshot,
  snapshotLoading,
  prices,
  flashMap,
  companies,
}: {
  portfolioTickers: string[];
  snapshot: PortfolioSnapshotItem[];
  snapshotLoading: boolean;
  prices: Record<string, { currentClose: number | null; dayOpen: number | null; asOf: string | null }>;
  flashMap: Record<string, "up" | "down">;
  companies: CompanyListItem[];
}) {
  const snapshotMap = useMemo(
    () => Object.fromEntries(snapshot.map((s) => [s.tickerRoot, s])),
    [snapshot]
  );

  if (portfolioTickers.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-3">
      {portfolioTickers.map((root) => {
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

        return (
          <div
            key={root}
            className="flex-1 min-w-[160px] rounded-lg border border-border bg-background/60 px-4 py-3 space-y-1"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-mono font-semibold text-primary">
                {snap?.ticker ?? root}
              </span>
              {dayChangePct != null && (
                <span
                  className={`text-[10px] font-mono tabular-nums ${
                    positive ? "text-green-400" : negative ? "text-red-400" : "text-muted-foreground"
                  }`}
                >
                  {positive ? "▲" : negative ? "▼" : ""} {Math.abs(dayChangePct).toFixed(2)}%
                </span>
              )}
            </div>
            <div className="text-[10px] text-muted-foreground truncate">
              {comp?.shortName ?? comp?.longName ?? root}
            </div>
            <div className="flex items-baseline gap-1.5">
              {snapshotLoading ? (
                <div className="h-4 w-16 bg-muted/30 rounded animate-pulse" />
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
                <span className="text-[10px] text-muted-foreground/50 font-mono">
                  ab. {fmt(dayOpen)}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 pt-0.5">
              {(["3", "7", "14"] as const).map((w) => {
                const val = snap?.changes?.[w];
                return (
                  <span key={w} className="flex items-center gap-0.5">
                    <span className="text-[9px] text-muted-foreground/50 font-mono">{w}d</span>
                    <span
                      className={`text-[10px] font-mono tabular-nums ${
                        val == null
                          ? "text-muted-foreground/30"
                          : val > 0
                            ? "text-green-400"
                            : val < 0
                              ? "text-red-400"
                              : "text-muted-foreground"
                      }`}
                    >
                      {val == null ? "—" : `${val > 0 ? "+" : ""}${val.toFixed(1)}%`}
                    </span>
                  </span>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Group analytics ────────────────────────────────────────────────────────────

function GroupAnalytics({ portfolioTickers }: { portfolioTickers: string[] }) {
  const [windowSize, setWindowSize] = useState<WindowSize>(7);

  const { data, loading, error } = useTrendsOverall(windowSize, undefined, portfolioTickers);
  const advisor = useAdvisor("overall", windowSize);

  const endLabel = data
    ? `${data.window.start} – ${data.window.end}`
    : null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70">
            Análise do grupo
          </span>
          {endLabel && (
            <span className="ml-2 text-[10px] font-mono text-muted-foreground/50">{endLabel}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70">Janela</span>
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
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard
          title="Sentimento ao longo do período"
          subtitle={data ? `${data.counts.total} artigos` : undefined}
        >
          <Body loading={loading} error={error} hasData={!!data} h={56}>
            {data && <WindowSentimentLine data={data.daily} />}
          </Body>
        </ChartCard>
        <ChartCard title="Volume diário">
          <Body loading={loading} error={error} hasData={!!data} h={56}>
            {data && <WindowVolumeBars data={data.daily} />}
          </Body>
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard title="Setores">
          <Body loading={loading} error={error} hasData={!!data} h={48}>
            {data && <SectorHeatmap data={{ sectorMatrix: data.sectorMatrix }} />}
          </Body>
        </ChartCard>
        <ChartCard title="Veículos">
          <Body loading={loading} error={error} hasData={!!data} h={48}>
            {data && (
              <SentimentByPublisher
                data={{ sentimentByPublisher: data.sentimentByPublisher }}
              />
            )}
          </Body>
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard title="Tickers citados">
          <Body loading={loading} error={error} hasData={!!data} h={48}>
            {data && <TopTickers data={{ topTickers: data.topTickers }} />}
          </Body>
        </ChartCard>
        <ChartCard title="Assuntos">
          <Body loading={loading} error={error} hasData={!!data} h={48}>
            {data && <TopSubjects data={{ topSubjects: data.topSubjects }} />}
          </Body>
        </ChartCard>
      </div>

      <AdvisorCard advisor={advisor} />
    </div>
  );
}

// ── Advisor card ───────────────────────────────────────────────────────────────

function AdvisorCard({ advisor }: { advisor: ReturnType<typeof useAdvisor> }) {
  const { data, loading, error, unavailable } = advisor;
  return (
    <ChartCard
      title="Análise do assessor"
      subtitle={
        data?.model
          ? `modelo: ${data.model}${
              data.generatedAt
                ? ` · ${new Date(data.generatedAt).toLocaleString("pt-BR")}`
                : ""
            }`
          : undefined
      }
    >
      {loading ? (
        <div className="space-y-3 animate-pulse">
          <div className="h-3 w-full bg-muted/30 rounded" />
          <div className="h-3 w-11/12 bg-muted/30 rounded" />
          <div className="h-3 w-3/4 bg-muted/30 rounded" />
          <div className="h-3 w-5/6 bg-muted/30 rounded mt-4" />
          <div className="h-3 w-2/3 bg-muted/30 rounded" />
        </div>
      ) : unavailable ? (
        <EmptyTile label="análise temporariamente indisponível" />
      ) : error ? (
        <EmptyTile label={`erro: ${error.message}`} />
      ) : data ? (
        <div className="space-y-4 text-sm font-mono leading-relaxed">
          {data.paragraphs.map((p, i) => (
            <p key={i}>{p}</p>
          ))}
        </div>
      ) : (
        <EmptyTile />
      )}
    </ChartCard>
  );
}

// ── Body helper ────────────────────────────────────────────────────────────────

function Body({
  loading,
  error,
  hasData,
  h,
  children,
}: {
  loading: boolean;
  error: Error | null;
  hasData: boolean;
  h: number;
  children: React.ReactNode;
}) {
  if (loading) return <div className="bg-muted/20 rounded animate-pulse" style={{ height: h * 4 }} />;
  if (error) return <EmptyTile label={`erro: ${error.message}`} />;
  if (!hasData) return <EmptyTile />;
  return <>{children}</>;
}

// ── Company selection table ────────────────────────────────────────────────────

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
            <span className="ml-2 text-primary/70">{portfolioTickers.length} selecionada{portfolioTickers.length > 1 ? "s" : ""}</span>
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
                          selected
                            ? "bg-primary/10 border-l-2 border-l-primary"
                            : "hover:bg-muted/30"
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

// ── Root ───────────────────────────────────────────────────────────────────────

export function PortfolioView({
  portfolioTickers,
  onPortfolioChange,
}: {
  portfolioTickers: string[];
  onPortfolioChange: (tickers: string[]) => void;
}) {
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
    if (portfolioTickers.length === 0) {
      setSnapshot([]);
      return;
    }
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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
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
      </div>

      {portfolioTickers.length > 0 && (
        <StockStrip
          portfolioTickers={portfolioTickers}
          snapshot={snapshot}
          snapshotLoading={snapshotLoading}
          prices={prices}
          flashMap={flashMap}
          companies={companies}
        />
      )}

      {portfolioTickers.length > 0 && (
        <GroupAnalytics portfolioTickers={portfolioTickers} />
      )}

      <CompanyTable
        companies={companies}
        companiesLoading={companiesLoading}
        portfolioTickers={portfolioTickers}
        onToggle={toggle}
      />
    </div>
  );
}
