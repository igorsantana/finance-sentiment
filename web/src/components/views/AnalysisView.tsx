import { useEffect, useMemo, useState } from "react";
import { ChartCard } from "../charts/ChartCard";
import { EmptyTile } from "../charts/_chart-axis";
import { SectorHeatmap } from "../charts/SectorHeatmap";
import { SentimentByPublisher } from "../charts/SentimentByPublisher";
import { SentimentVsPriceChart } from "../charts/SentimentVsPriceChart";
import { TopSubjects } from "../charts/TopSubjects";
import { TopTickers } from "../charts/TopTickers";
import { WindowSentimentLine } from "../charts/WindowSentimentLine";
import { WindowVolumeBars } from "../charts/WindowVolumeBars";
import { Combobox, type ComboboxOption } from "../ui/combobox";
import { useAdvisor } from "../../hooks/useAdvisor";
import { useTrendsCompany } from "../../hooks/useTrendsCompany";
import { useTrendsOverall } from "../../hooks/useTrendsOverall";
import type {
  AdvisorScope,
  WindowCompany,
  WindowOverall,
  WindowSize,
} from "../../api";
import { formatPtBr } from "../../lib/date";

const WINDOW_OPTIONS: WindowSize[] = [3, 7, 14];
type Scope = "overall" | "company";

export function AnalysisView({
  portfolioFilter = false,
  portfolioTickers = [],
}: {
  portfolioFilter?: boolean;
  portfolioTickers?: string[];
} = {}) {
  const [windowSize, setWindowSize] = useState<WindowSize>(7);
  const [scope, setScope] = useState<Scope>("overall");

  const filterTickers =
    portfolioFilter && portfolioTickers.length > 0 ? portfolioTickers : undefined;

  const {
    data: overallData,
    loading: overallLoading,
    error: overallError,
  } = useTrendsOverall(windowSize, undefined, filterTickers);

  // Combobox source: a separate 7d fetch keeps the list stable when the user
  // narrows the window to 3d. No ticker filter here — we want all tickers for
  // the combobox even when the portfolio filter is active.
  const { data: overall7 } = useTrendsOverall(7);

  const allTickerOptions = useMemo<ComboboxOption[]>(() => {
    if (!overall7) return [];
    return overall7.topTickers.map((t) => ({
      value: t.ticker,
      label: t.ticker,
      hint: `${t.count} art.`,
    }));
  }, [overall7]);

  const tickerOptions = useMemo<ComboboxOption[]>(() => {
    if (!portfolioFilter || portfolioTickers.length === 0) return allTickerOptions;
    const set = new Set(portfolioTickers);
    const filtered = allTickerOptions.filter((o) => set.has(o.value));
    if (filtered.length > 0) return filtered;
    // Portfolio tickers not in the 7d window — show them anyway without hints
    return portfolioTickers.map((t) => ({ value: t, label: t }));
  }, [allTickerOptions, portfolioFilter, portfolioTickers]);

  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  useEffect(() => {
    if (portfolioFilter && portfolioTickers.length > 0) {
      // When filter activates, default to first portfolio ticker
      if (!portfolioTickers.includes(selectedTicker ?? "")) {
        setSelectedTicker(portfolioTickers[0]);
      }
      return;
    }
    if (selectedTicker && tickerOptions.some((o) => o.value === selectedTicker)) return;
    setSelectedTicker(tickerOptions[0]?.value ?? null);
  }, [tickerOptions, selectedTicker, portfolioFilter, portfolioTickers]);

  const {
    data: companyData,
    loading: companyLoading,
    error: companyError,
  } = useTrendsCompany(scope === "company" ? selectedTicker : null, windowSize);

  const advisorScope: AdvisorScope =
    scope === "overall" || !selectedTicker
      ? "overall"
      : { ticker: selectedTicker };
  const advisor = useAdvisor(advisorScope, windowSize);

  const endLabel = overallData
    ? `${formatPtBr(overallData.window.start)} – ${formatPtBr(overallData.window.end)}`
    : "—";

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h2 className="font-mono uppercase tracking-[0.25em] text-xs text-muted-foreground mb-1">
            Análise
          </h2>
          <p className="text-2xl font-semibold font-mono">
            {windowSize} dias <span className="text-muted-foreground/60">·</span>{" "}
            <span className="text-base text-muted-foreground">{endLabel}</span>
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <ToggleGroup
            label="Janela"
            options={WINDOW_OPTIONS.map((n) => ({ id: n, label: `${n}d` }))}
            value={windowSize}
            onChange={setWindowSize}
          />
          <ToggleGroup
            label="Escopo"
            options={[
              { id: "overall", label: "Mercado" },
              { id: "company", label: "Empresa" },
            ]}
            value={scope}
            onChange={setScope}
          />
          {scope === "company" && (
            <Combobox
              value={selectedTicker}
              options={tickerOptions}
              onChange={setSelectedTicker}
              placeholder="Selecione um ticker"
            />
          )}
        </div>
      </div>

      {scope === "overall" ? (
        <OverallPanel
          data={overallData}
          loading={overallLoading}
          error={overallError}
        />
      ) : (
        <CompanyPanel
          data={companyData}
          loading={companyLoading}
          error={companyError}
          hasSelection={!!selectedTicker}
        />
      )}

      <AdvisorCard advisor={advisor} />
    </div>
  );
}

function ToggleGroup<T extends string | number>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { id: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70">
        {label}
      </span>
      <div
        role="tablist"
        aria-label={label}
        className="inline-flex border border-border rounded-md p-0.5 bg-muted/30"
      >
        {options.map((opt) => {
          const active = opt.id === value;
          return (
            <button
              key={String(opt.id)}
              role="tab"
              aria-selected={active}
              onClick={() => onChange(opt.id)}
              className={`px-3 py-1.5 text-xs font-mono uppercase tracking-widest rounded-sm transition-all ${
                active
                  ? "bg-primary/15 text-primary border neon-edge"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function OverallPanel({
  data,
  loading,
  error,
}: {
  data: WindowOverall | null;
  loading: boolean;
  error: Error | null;
}) {
  return (
    <div className="space-y-6">
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
      <ChartCard title="Tickers mais citados">
        <Body loading={loading} error={error} hasData={!!data} h={56}>
          {data && <TopTickers data={{ topTickers: data.topTickers }} />}
        </Body>
      </ChartCard>
    </div>
  );
}

function CompanyPanel({
  data,
  loading,
  error,
  hasSelection,
}: {
  data: WindowCompany | null;
  loading: boolean;
  error: Error | null;
  hasSelection: boolean;
}) {
  if (!hasSelection) {
    return (
      <ChartCard title="Empresa">
        <EmptyTile label="— selecione uma empresa —" />
      </ChartCard>
    );
  }
  const corrLabel =
    data?.correlation === null || data?.correlation === undefined
      ? null
      : `r = ${data.correlation >= 0 ? "+" : ""}${data.correlation.toFixed(2)}`;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard
          title="Sentimento × Cotação"
          subtitle={corrLabel ?? undefined}
        >
          <Body loading={loading} error={error} hasData={!!data} h={72}>
            {data && (
              <SentimentVsPriceChart data={{ points: data.daily }} />
            )}
          </Body>
        </ChartCard>
        <ChartCard title="Volume × Sentimento">
          <Body loading={loading} error={error} hasData={!!data} h={72}>
            {data && <WindowVolumeBars data={data.daily} />}
          </Body>
        </ChartCard>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard title="Top assuntos">
          <Body loading={loading} error={error} hasData={!!data} h={48}>
            {data && <TopSubjects data={{ topSubjects: data.topSubjects }} />}
          </Body>
        </ChartCard>
        <ChartCard title="Veículos">
          <Body loading={loading} error={error} hasData={!!data} h={48}>
            {data && (
              <SentimentByPublisher
                data={{
                  sentimentByPublisher: data.topPublishers.map((p) => ({
                    site: p.site,
                    positive: 0,
                    neutral: 0,
                    negative: 0,
                    total: p.count,
                  })),
                }}
              />
            )}
          </Body>
        </ChartCard>
      </div>
    </div>
  );
}

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
  if (loading) {
    return (
      <div
        className="bg-muted/20 rounded animate-pulse"
        style={{ height: h * 4 }}
      />
    );
  }
  if (error) return <EmptyTile label={`erro: ${error.message}`} />;
  if (!hasData) return <EmptyTile />;
  return <>{children}</>;
}
