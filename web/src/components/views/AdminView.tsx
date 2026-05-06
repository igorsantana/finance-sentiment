import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, Search, Shield, ShieldCheck, X } from "lucide-react";
import {
  AdminArticle,
  CompanyListItem,
  getAdminArticles,
  getCompanies,
  postJudgment,
} from "../../api";
import { SENTIMENT_COLORS } from "../../lib/sentiment";
import { formatPtBr } from "../../lib/date";
import { toIsoDate } from "../../api";

const CORRECT_PIN = "0000";

// ---------- PIN gate ----------

function PinGate({ onUnlock }: { onUnlock: () => void }) {
  const [digits, setDigits] = useState<string[]>([]);
  const [shake, setShake] = useState(false);

  const handleDigit = (d: string) => {
    if (digits.length >= 4) return;
    const next = [...digits, d];
    setDigits(next);
    if (next.length === 4) {
      const pin = next.join("");
      if (pin === CORRECT_PIN) {
        sessionStorage.setItem("admin_unlocked", "1");
        onUnlock();
      } else {
        setShake(true);
        setTimeout(() => { setDigits([]); setShake(false); }, 600);
      }
    }
  };

  const handleBackspace = () => setDigits((d) => d.slice(0, -1));

  const keyLayout = [
    ["1", "2", "3"],
    ["4", "5", "6"],
    ["7", "8", "9"],
    ["⌫", "0", "✓"],
  ];

  return (
    <div className="flex flex-col items-center justify-center min-h-[70vh] gap-8">
      <div className="flex items-center gap-3 text-primary">
        <Shield className="h-8 w-8 neon-flicker" />
        <span className="font-mono text-xl tracking-[0.3em] uppercase">Admin Access</span>
      </div>

      <div className={`flex gap-4 ${shake ? "animate-shake" : ""}`}>
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className={`w-10 h-10 rounded border flex items-center justify-center font-mono text-lg transition-colors ${
              i < digits.length
                ? "border-primary text-primary shadow-[0_0_8px_hsl(var(--primary))]"
                : "border-border text-muted-foreground"
            }`}
          >
            {i < digits.length ? "●" : "○"}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-2">
        {keyLayout.flat().map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => {
              if (key === "⌫") handleBackspace();
              else if (key === "✓") { /* auto-submit on 4 digits */ }
              else handleDigit(key);
            }}
            className={`w-16 h-16 rounded border font-mono text-xl transition-all
              ${key === "⌫" || key === "✓"
                ? "border-border text-muted-foreground hover:text-foreground hover:border-foreground"
                : "border-primary/40 text-primary hover:border-primary hover:bg-primary/10 hover:shadow-[0_0_12px_hsl(var(--primary)/0.3)]"
              }
              active:scale-95
            `}
          >
            {key}
          </button>
        ))}
      </div>

      <p className="text-xs font-mono text-muted-foreground/60 tracking-widest uppercase">
        — acesso restrito —
      </p>
    </div>
  );
}

// ---------- Judgment labels ----------

type JudgmentLabel = "positive" | "neutral" | "negative" | "skip" | "bad_match";

const LABELS: Array<{ id: JudgmentLabel; label: string; color: string }> = [
  { id: "positive",  label: "✓ Correto+",  color: "text-green-400 border-green-400/50 hover:bg-green-400/10" },
  { id: "neutral",   label: "= Neutro",    color: "text-yellow-400 border-yellow-400/50 hover:bg-yellow-400/10" },
  { id: "negative",  label: "✗ Incorreto", color: "text-red-400 border-red-400/50 hover:bg-red-400/10" },
  { id: "skip",      label: "⤫ Skip",      color: "text-muted-foreground border-border hover:bg-muted/40" },
  { id: "bad_match", label: "⚠ Má assoc.", color: "text-orange-400 border-orange-400/50 hover:bg-orange-400/10" },
];

// ---------- Article card ----------

function ArticleCard({
  article,
  active,
  onActivate,
  onJudge,
}: {
  article: AdminArticle;
  active: boolean;
  onActivate: () => void;
  onJudge: (label: JudgmentLabel) => void;
}) {
  const sentColor =
    article.sentiment === "positive"
      ? SENTIMENT_COLORS.positive
      : article.sentiment === "negative"
      ? SENTIMENT_COLORS.negative
      : SENTIMENT_COLORS.neutral;

  return (
    <div
      onClick={onActivate}
      className={`rounded-lg border p-4 cursor-pointer transition-all ${
        active
          ? "border-primary bg-primary/5 shadow-[0_0_12px_hsl(var(--primary)/0.2)]"
          : article.judgment
          ? "border-border/60 bg-muted/10 opacity-70"
          : "border-border hover:border-primary/40 hover:bg-muted/10"
      }`}
    >
      <div className="flex items-start gap-3 mb-3">
        <div className="flex-1 min-w-0">
          <a
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="font-medium text-sm text-foreground hover:text-primary line-clamp-2"
          >
            {article.title ?? article.url}
          </a>
          <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground font-mono">
            {article.site && (
              <span className="px-1.5 py-0.5 rounded bg-muted/60 border border-border/50">
                {article.site}
              </span>
            )}
            {article.publishedAt && (
              <span>{formatPtBr(article.publishedAt.slice(0, 10))}</span>
            )}
            {article.sentiment && (
              <span style={{ color: sentColor }}>
                {article.sentiment}
                {article.sentimentScore != null
                  ? ` (${(article.sentimentScore * 100).toFixed(0)}%)`
                  : ""}
              </span>
            )}
          </div>
        </div>

        {article.judgment && (
          <span
            className={`shrink-0 text-xs font-mono px-2 py-0.5 rounded border ${
              LABELS.find((l) => l.id === article.judgment!.label)?.color ?? ""
            }`}
          >
            {article.judgment.label}
          </span>
        )}
      </div>

      {article.matchedTickers.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {article.matchedTickers.map((t) => (
            <span
              key={t}
              className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-primary/10 border border-primary/20 text-primary"
            >
              {t}
            </span>
          ))}
        </div>
      )}

      {active && (
        <div
          className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-border/40"
          onClick={(e) => e.stopPropagation()}
        >
          {LABELS.map((l, idx) => (
            <button
              key={l.id}
              type="button"
              onClick={() => onJudge(l.id)}
              title={`${l.label} [${idx + 1}]`}
              className={`text-xs font-mono px-3 py-1.5 rounded border transition-all active:scale-95 ${l.color} ${
                article.judgment?.label === l.id
                  ? "ring-1 ring-current shadow-[0_0_8px_currentColor]"
                  : ""
              }`}
            >
              {l.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------- Review panel ----------

function ReviewPanel() {
  const today = toIsoDate(new Date());
  const [dateIso, setDateIso] = useState(today);
  const [ticker, setTicker] = useState("");
  const [articles, setArticles] = useState<AdminArticle[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeIdx, setActiveIdx] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(
    (d: string, t: string) => {
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setLoading(true);
      setActiveIdx(null);
      getAdminArticles(d, t || undefined, ctrl.signal)
        .then((rows) => { setArticles(rows); setLoading(false); })
        .catch((e) => { if ((e as Error).name !== "AbortError") setLoading(false); });
    },
    [],
  );

  useEffect(() => { load(dateIso, ticker); }, [dateIso, ticker, load]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.key === "ArrowDown" || e.key === "j") {
        setActiveIdx((i) => Math.min((i ?? -1) + 1, articles.length - 1));
      } else if (e.key === "ArrowUp" || e.key === "k") {
        setActiveIdx((i) => Math.max((i ?? 0) - 1, 0));
      } else if (activeIdx !== null && e.key >= "1" && e.key <= "5") {
        const label = LABELS[parseInt(e.key) - 1].id;
        handleJudge(activeIdx, label);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [activeIdx, articles]);

  const handleJudge = (idx: number, label: JudgmentLabel) => {
    const article = articles[idx];
    if (!article) return;
    postJudgment(article.url, label).then(() => {
      setArticles((prev) =>
        prev.map((a, i) =>
          i === idx ? { ...a, judgment: { label, notes: "" } } : a,
        ),
      );
      setActiveIdx((i) => (i !== null && i < articles.length - 1 ? i + 1 : i));
    });
  };

  const labeled = articles.filter((a) => a.judgment).length;

  return (
    <div>
      <div className="flex items-center gap-4 mb-6 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-muted-foreground uppercase tracking-widest">Data</span>
          <input
            type="date"
            value={dateIso}
            onChange={(e) => setDateIso(e.target.value)}
            className="font-mono text-sm bg-background border border-border rounded px-3 py-1.5 text-foreground focus:border-primary focus:outline-none"
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-muted-foreground uppercase tracking-widest">Ticker</span>
          <input
            type="text"
            placeholder="ex: VALE"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            className="font-mono text-sm bg-background border border-border rounded px-3 py-1.5 text-foreground focus:border-primary focus:outline-none w-28"
          />
        </div>
        <div className="ml-auto text-xs font-mono text-muted-foreground">
          {labeled}/{articles.length} avaliados
        </div>
      </div>

      <div className="flex gap-2 flex-wrap mb-4 text-[10px] font-mono text-muted-foreground/70">
        <span>↑↓ navegar</span>
        <span>·</span>
        {LABELS.map((l, i) => (
          <span key={l.id}>[{i + 1}] {l.label}</span>
        ))}
      </div>

      {loading ? (
        <div className="text-xs font-mono text-muted-foreground animate-pulse">carregando…</div>
      ) : articles.length === 0 ? (
        <div className="text-xs font-mono text-muted-foreground">— sem artigos —</div>
      ) : (
        <div className="flex flex-col gap-3">
          {articles.map((a, i) => (
            <ArticleCard
              key={a.url}
              article={a}
              active={activeIdx === i}
              onActivate={() => setActiveIdx(i === activeIdx ? null : i)}
              onJudge={(label) => handleJudge(i, label)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------- Portfolio config panel ----------

function formatMarketCap(v: number | null): string {
  if (v == null) return "—";
  if (v >= 1e12) return `R$ ${(v / 1e12).toFixed(1)}T`;
  if (v >= 1e9) return `R$ ${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `R$ ${(v / 1e6).toFixed(0)}M`;
  return `R$ ${v.toLocaleString("pt-BR")}`;
}

function PortfolioConfigPanel({
  portfolioTickers,
  onPortfolioChange,
  quantities,
  onQtyChange,
  avgPrices,
  onAvgChange,
}: {
  portfolioTickers: string[];
  onPortfolioChange: (tickers: string[]) => void;
  quantities: Record<string, number>;
  onQtyChange: (root: string, qty: number) => void;
  avgPrices: Record<string, number>;
  onAvgChange: (root: string, avg: number) => void;
}) {
  const [companies, setCompanies] = useState<CompanyListItem[]>([]);
  const [companiesLoading, setCompaniesLoading] = useState(true);
  const [selectorOpen, setSelectorOpen] = useState(portfolioTickers.length === 0);
  const [search, setSearch] = useState("");

  useEffect(() => {
    const ctrl = new AbortController();
    setCompaniesLoading(true);
    getCompanies(ctrl.signal)
      .then(setCompanies)
      .catch(() => {})
      .finally(() => setCompaniesLoading(false));
    return () => ctrl.abort();
  }, []);

  const filtered = companies.filter((c) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      c.tickerRoot.toLowerCase().includes(q) ||
      c.ticker.toLowerCase().includes(q) ||
      (c.shortName ?? "").toLowerCase().includes(q) ||
      (c.longName ?? "").toLowerCase().includes(q)
    );
  });

  const toggle = (root: string) => {
    if (portfolioTickers.includes(root)) {
      onPortfolioChange(portfolioTickers.filter((t) => t !== root));
    } else {
      onPortfolioChange([...portfolioTickers, root]);
    }
  };

  const th = "px-4 py-2 text-left text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70 whitespace-nowrap";
  const td = "px-4 py-2 text-xs font-mono whitespace-nowrap";

  return (
    <div className="space-y-6">
      {/* Company selector */}
      <div className="rounded-lg border border-border bg-background/60 overflow-hidden">
        <button
          type="button"
          onClick={() => setSelectorOpen((v) => !v)}
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
            className={`h-3.5 w-3.5 text-muted-foreground/50 transition-transform ${selectorOpen ? "rotate-0" : "-rotate-90"}`}
          />
        </button>

        {selectorOpen && (
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
                          onClick={() => toggle(c.tickerRoot)}
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

      {/* Per-ticker qty / avg price inputs */}
      {portfolioTickers.length > 0 && (
        <div className="rounded-lg border border-border bg-background/60 overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <span className="text-xs font-mono uppercase tracking-widest text-muted-foreground/70">
              Posições
            </span>
          </div>
          <table className="w-full">
            <thead className="border-b border-border bg-muted/10">
              <tr>
                <th className={th}>Ativo</th>
                <th className={`${th} text-right`}>Quantidade</th>
                <th className={`${th} text-right`}>Preço médio (R$)</th>
              </tr>
            </thead>
            <tbody>
              {portfolioTickers.map((root) => {
                const comp = companies.find((c) => c.tickerRoot === root);
                return (
                  <tr key={root} className="border-b border-border/40">
                    <td className={`${td}`}>
                      <span className="text-primary font-semibold">{root}</span>
                      {comp && (
                        <span className="ml-2 text-muted-foreground/60 text-[10px]">
                          {comp.shortName ?? comp.longName}
                        </span>
                      )}
                    </td>
                    <td className={`${td} text-right`}>
                      <input
                        type="number"
                        min={0}
                        value={quantities[root] || ""}
                        onChange={(e) => {
                          const v = parseInt(e.target.value, 10);
                          onQtyChange(root, isNaN(v) || v < 0 ? 0 : v);
                        }}
                        placeholder="0"
                        className="w-28 bg-muted/20 border border-border/60 rounded px-2 py-1 text-xs font-mono text-right outline-none focus:border-primary/50 tabular-nums"
                      />
                    </td>
                    <td className={`${td} text-right`}>
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
                        className="w-28 bg-muted/20 border border-border/60 rounded px-2 py-1 text-xs font-mono text-right outline-none focus:border-primary/50 tabular-nums"
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------- Root export ----------

type AdminTab = "review" | "carteira";

export function AdminView({
  portfolioTickers,
  onPortfolioChange,
  quantities,
  onQtyChange,
  avgPrices,
  onAvgChange,
}: {
  portfolioTickers: string[];
  onPortfolioChange: (tickers: string[]) => void;
  quantities: Record<string, number>;
  onQtyChange: (root: string, qty: number) => void;
  avgPrices: Record<string, number>;
  onAvgChange: (root: string, avg: number) => void;
}) {
  const [unlocked, setUnlocked] = useState(
    () => sessionStorage.getItem("admin_unlocked") === "1",
  );
  const [tab, setTab] = useState<AdminTab>("review");

  const TABS: Array<{ id: AdminTab; label: string }> = [
    { id: "review", label: "Avaliação" },
    { id: "carteira", label: "Carteira" },
  ];

  return (
    <div>
      <div className="flex items-center gap-3 mb-8">
        <ShieldCheck className="h-5 w-5 text-primary" />
        <h1 className="font-mono text-lg tracking-[0.2em] uppercase text-foreground">
          Admin<span className="text-primary"> · {tab === "review" ? "Review" : "Carteira"}</span>
        </h1>
      </div>

      {unlocked ? (
        <>
          {/* Tab navigation */}
          <div className="flex gap-1 mb-6 border-b border-border pb-0">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={`px-4 py-2 text-xs font-mono uppercase tracking-widest transition-colors border-b-2 -mb-px ${
                  tab === t.id
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {tab === "review" ? (
            <ReviewPanel />
          ) : (
            <PortfolioConfigPanel
              portfolioTickers={portfolioTickers}
              onPortfolioChange={onPortfolioChange}
              quantities={quantities}
              onQtyChange={onQtyChange}
              avgPrices={avgPrices}
              onAvgChange={onAvgChange}
            />
          )}
        </>
      ) : (
        <PinGate onUnlock={() => setUnlocked(true)} />
      )}
    </div>
  );
}
