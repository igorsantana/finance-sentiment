import { useEffect, useMemo, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { getCompanies, getPortfolioSnapshot } from "../../api";
import type { CompanyListItem, PortfolioSnapshotItem } from "../../api";
import { usePortfolioStream } from "../../hooks/usePortfolioStream";

function fmt(n: number | null | undefined, decimals = 2): string {
  if (n == null) return "—";
  return n.toFixed(decimals);
}

function ChangeCell({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-muted-foreground/50">—</span>;
  const positive = value > 0;
  const negative = value < 0;
  return (
    <span
      className={
        positive ? "text-green-400" : negative ? "text-red-400" : "text-muted-foreground"
      }
    >
      {positive ? "+" : ""}
      {value.toFixed(2)}%
    </span>
  );
}

function formatMarketCap(v: number | null): string {
  if (v == null) return "—";
  if (v >= 1e12) return `R$ ${(v / 1e12).toFixed(1)}T`;
  if (v >= 1e9) return `R$ ${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `R$ ${(v / 1e6).toFixed(0)}M`;
  return `R$ ${v.toLocaleString("pt-BR")}`;
}

export function PortfolioView({
  portfolioTickers,
  onPortfolioChange,
}: {
  portfolioTickers: string[];
  onPortfolioChange: (tickers: string[]) => void;
}) {
  const [companies, setCompanies] = useState<CompanyListItem[]>([]);
  const [companiesLoading, setCompaniesLoading] = useState(true);
  const [search, setSearch] = useState("");

  const [snapshot, setSnapshot] = useState<PortfolioSnapshotItem[]>([]);
  const [snapshotLoading, setSnapshotLoading] = useState(false);

  const { prices, connected } = usePortfolioStream(portfolioTickers);

  // Track price changes to trigger flash animation
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

  const filteredCompanies = useMemo(() => {
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

  const toggle = (root: string) => {
    if (portfolioTickers.includes(root)) {
      onPortfolioChange(portfolioTickers.filter((t) => t !== root));
    } else {
      onPortfolioChange([...portfolioTickers, root]);
    }
  };

  const snapshotMap = useMemo(
    () => Object.fromEntries(snapshot.map((s) => [s.tickerRoot, s])),
    [snapshot]
  );

  const th = "px-4 py-2 text-left text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70 whitespace-nowrap";
  const td = "px-4 py-2 text-xs font-mono whitespace-nowrap";

  return (
    <div className="space-y-6">
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

      {/* Company selection table */}
      <div className="rounded-lg border border-border bg-background/60 overflow-hidden">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-3">
          <span className="text-xs font-mono uppercase tracking-widest text-muted-foreground/70">
            Selecionar empresas
          </span>
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

        <div className="max-h-72 overflow-y-auto">
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
                {filteredCompanies.map((c) => {
                  const selected = portfolioTickers.includes(c.tickerRoot);
                  return (
                    <tr
                      key={c.tickerRoot}
                      onClick={() => toggle(c.tickerRoot)}
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
      </div>

      {/* Portfolio dashboard */}
      {portfolioTickers.length > 0 && (
        <div className="rounded-lg border border-border bg-background/60 overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <span className="text-xs font-mono uppercase tracking-widest text-muted-foreground/70">
              Carteira
            </span>
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
          </div>

          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-border">
                <tr>
                  <th className={th}>Nome</th>
                  <th className={th}>Ticker</th>
                  <th className={`${th} text-right`}>Abertura</th>
                  <th className={`${th} text-right`}>Preço atual</th>
                  <th className={`${th} text-right`}>Var. 3d</th>
                  <th className={`${th} text-right`}>Var. 7d</th>
                  <th className={`${th} text-right`}>Var. 14d</th>
                </tr>
              </thead>
              <tbody>
                {snapshotLoading
                  ? portfolioTickers.map((root) => (
                      <tr key={root} className="border-b border-border/40 animate-pulse">
                        {Array.from({ length: 7 }).map((_, i) => (
                          <td key={i} className={td}>
                            <div className="h-3 bg-muted/30 rounded w-16" />
                          </td>
                        ))}
                      </tr>
                    ))
                  : portfolioTickers.map((root) => {
                      const snap = snapshotMap[root];
                      const live = prices[root];
                      const currentClose = live?.currentClose ?? snap?.currentClose;
                      const dayOpen = live?.dayOpen ?? snap?.dayOpen;
                      const asOf = live?.asOf ?? snap?.asOf;
                      const comp = companies.find((c) => c.tickerRoot === root);

                      return (
                        <tr
                          key={root}
                          className="border-b border-border/40 hover:bg-muted/20 transition-colors"
                        >
                          <td className={`${td} text-foreground`}>
                            {comp?.shortName ?? comp?.longName ?? root}
                          </td>
                          <td className={`${td} text-primary font-semibold`}>
                            {snap?.ticker ?? root}
                          </td>
                          <td className={`${td} text-right tabular-nums text-muted-foreground`}>
                            {fmt(dayOpen)}
                          </td>
                          <td className={`${td} text-right tabular-nums`}>
                            <span
                              key={`${root}-${currentClose}`}
                              className={
                                flashMap[root] === "up"
                                  ? "price-flash-up"
                                  : flashMap[root] === "down"
                                    ? "price-flash-down"
                                    : "text-foreground"
                              }
                            >
                              {fmt(currentClose)}
                            </span>
                            {asOf && (
                              <span className="ml-1 text-[9px] text-muted-foreground/50">
                                {asOf}
                              </span>
                            )}
                          </td>
                          <td className={`${td} text-right tabular-nums`}>
                            <ChangeCell value={snap?.changes?.["3"]} />
                          </td>
                          <td className={`${td} text-right tabular-nums`}>
                            <ChangeCell value={snap?.changes?.["7"]} />
                          </td>
                          <td className={`${td} text-right tabular-nums`}>
                            <ChangeCell value={snap?.changes?.["14"]} />
                          </td>
                        </tr>
                      );
                    })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
