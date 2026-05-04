import { useEffect, useMemo, useState } from "react";
import { ChartCard } from "./charts/ChartCard";
import { EmptyTile } from "./charts/_chart-axis";
import { SentimentVsPriceChart } from "./charts/SentimentVsPriceChart";
import { StockCandleChart } from "./charts/StockCandleChart";
import { Combobox, type ComboboxOption } from "./ui/combobox";
import { useCompanySummary } from "../hooks/useCompanySummary";
import { useReport } from "../hooks/useReport";
import { useSentimentSeries } from "../hooks/useSentimentSeries";
import { useStockOhlc } from "../hooks/useStockOhlc";
import { formatPtBr } from "../lib/date";
import { SENTIMENT_COLORS, SENTIMENT_LABEL_PT, type SentimentTone } from "../lib/sentiment";

export type CompanyPanelProps = {
  date: string | null;
};

export function CompanyPanel({ date }: CompanyPanelProps) {
  const { data: report, loading: reportLoading } = useReport(date);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);

  const options = useMemo<ComboboxOption[]>(() => {
    if (!report) return [];
    // top_companies and top_tickers are independent aggregations; the FE has
    // no ticker→name map, so we display the ticker root as the label and let
    // the summary endpoint return the human-readable name on selection.
    return report.topTickers.map((t) => ({
      value: t.ticker,
      label: t.ticker,
      hint: `${t.count} art.`,
    }));
  }, [report]);

  useEffect(() => {
    if (selectedTicker && options.some((o) => o.value === selectedTicker)) return;
    setSelectedTicker(options[0]?.value ?? null);
  }, [options, selectedTicker]);

  const { data: summary, loading: summaryLoading, error: summaryError } =
    useCompanySummary(selectedTicker, date);
  const { data: ohlc, loading: ohlcLoading, error: ohlcError } =
    useStockOhlc(selectedTicker, date);
  const { data: series, loading: seriesLoading, error: seriesError } =
    useSentimentSeries(selectedTicker, date);

  const corrLabel =
    series?.correlation === null || series?.correlation === undefined
      ? null
      : `r = ${series.correlation >= 0 ? "+" : ""}${series.correlation.toFixed(2)}`;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70">
          Empresa
        </span>
        <Combobox
          value={selectedTicker}
          options={options}
          onChange={setSelectedTicker}
          placeholder={reportLoading ? "carregando…" : "Selecione um ticker"}
        />
        {summary?.name && (
          <span className="text-sm font-mono text-muted-foreground">
            · {summary.name}
          </span>
        )}
      </div>

      <ChartCard
        title="Resumo da empresa"
        subtitle={summary?.model ?? undefined}
      >
        <SummaryBody
          loading={summaryLoading}
          error={summaryError}
          summary={summary}
          hasSelection={!!selectedTicker}
        />
      </ChartCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard
          title="Cotação"
          subtitle={ohlc ? `±10 dias · ${formatPtBr(date)}` : undefined}
        >
          <OhlcBody
            loading={ohlcLoading}
            error={ohlcError}
            data={ohlc}
            hasSelection={!!selectedTicker}
          />
        </ChartCard>

        <ChartCard
          title="Preço × sentimento"
          subtitle={corrLabel ?? "±10 dias"}
        >
          <SeriesBody
            loading={seriesLoading}
            error={seriesError}
            data={series}
            hasSelection={!!selectedTicker}
          />
        </ChartCard>
      </div>
    </div>
  );
}

function SeriesBody({
  loading,
  error,
  data,
  hasSelection,
}: {
  loading: boolean;
  error: Error | null;
  data: ReturnType<typeof useSentimentSeries>["data"];
  hasSelection: boolean;
}) {
  if (!hasSelection) {
    return <EmptyTile label="— selecione uma empresa —" />;
  }
  if (loading) {
    return <div className="h-72 bg-muted/20 rounded animate-pulse" />;
  }
  if (error) {
    return <EmptyTile label={`erro: ${error.message}`} />;
  }
  if (!data || data.points.length === 0) {
    return <EmptyTile label="— sem dados —" />;
  }
  return <SentimentVsPriceChart data={data} />;
}

function SummaryBody({
  loading,
  error,
  summary,
  hasSelection,
}: {
  loading: boolean;
  error: Error | null;
  summary: ReturnType<typeof useCompanySummary>["data"];
  hasSelection: boolean;
}) {
  if (!hasSelection) {
    return <EmptyTile label="— selecione uma empresa —" />;
  }
  if (loading) {
    return (
      <div className="space-y-3 animate-pulse">
        <div className="h-4 w-1/3 bg-muted/40 rounded" />
        <div className="h-3 w-full bg-muted/30 rounded" />
        <div className="h-3 w-5/6 bg-muted/30 rounded" />
        <div className="h-3 w-2/3 bg-muted/30 rounded" />
      </div>
    );
  }
  if (error) {
    return <EmptyTile label={`erro: ${error.message}`} />;
  }
  if (!summary) {
    return <EmptyTile label="ainda sem resumo — execute o pipeline" />;
  }
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <BulletColumn
          title="Pontos positivos"
          tone="positive"
          items={summary.good}
        />
        <BulletColumn
          title="Pontos negativos"
          tone="negative"
          items={summary.bad}
        />
      </div>

      {summary.articles.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70">
            Artigos analisados
          </h4>
          <ul className="space-y-1.5">
            {summary.articles.map((a) => (
              <li
                key={a.url}
                className="flex items-start gap-2 text-xs font-mono"
              >
                <SentimentChip sentiment={a.sentiment} />
                <span className="text-muted-foreground/80 shrink-0">
                  {a.site ?? "—"}
                </span>
                <a
                  href={a.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-foreground hover:text-primary truncate"
                >
                  {a.title ?? a.url}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function OhlcBody({
  loading,
  error,
  data,
  hasSelection,
}: {
  loading: boolean;
  error: Error | null;
  data: ReturnType<typeof useStockOhlc>["data"];
  hasSelection: boolean;
}) {
  if (!hasSelection) {
    return <EmptyTile label="— selecione uma empresa —" />;
  }
  if (loading) {
    return <div className="h-72 bg-muted/20 rounded animate-pulse" />;
  }
  if (error) {
    return <EmptyTile label={`erro: ${error.message}`} />;
  }
  if (!data || data.bars.length === 0) {
    return <EmptyTile label="— sem cotação para o ticker —" />;
  }
  return <StockCandleChart data={data} />;
}

function BulletColumn({
  title,
  tone,
  items,
}: {
  title: string;
  tone: SentimentTone;
  items: string[];
}) {
  const color = SENTIMENT_COLORS[tone];
  return (
    <div>
      <h4
        className="text-[10px] font-mono uppercase tracking-widest mb-2"
        style={{ color }}
      >
        {title}
      </h4>
      {items.length === 0 ? (
        <p className="text-xs font-mono text-muted-foreground/70">— vazio —</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((item, i) => (
            <li key={i} className="flex gap-2 text-sm leading-snug">
              <span style={{ color }} className="shrink-0">
                ▸
              </span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SentimentChip({ sentiment }: { sentiment: string | null }) {
  const tone: SentimentTone =
    sentiment === "positive" || sentiment === "negative" || sentiment === "neutral"
      ? sentiment
      : "neutral";
  const color = SENTIMENT_COLORS[tone];
  return (
    <span
      className="inline-block px-1.5 py-0.5 rounded-sm border text-[9px] uppercase tracking-widest shrink-0"
      style={{ color, borderColor: color }}
      title={SENTIMENT_LABEL_PT[tone]}
    >
      {tone === "positive" ? "+" : tone === "negative" ? "−" : "="}
    </span>
  );
}
