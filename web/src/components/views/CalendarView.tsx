import { useState } from "react";
import { ChevronLeft, ChevronRight, ListOrdered, Loader2, PlayCircle, X } from "lucide-react";
import { useCalendar } from "../../hooks/useCalendar";
import type { CalendarDay } from "../../api";

const WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];

const MONTH_NAMES = [
  "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
  "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
];

const WEEKEND_HATCH = "repeating-linear-gradient(135deg, transparent, transparent 4px, hsl(var(--muted-foreground) / 0.10) 4px, hsl(var(--muted-foreground) / 0.10) 5px)";
const WEEKDAY_GRADIENT = "linear-gradient(180deg, hsl(var(--primary) / 0.03) 0%, transparent 60%)";

function toMonthKey(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}

function sentimentColor(net: number | null): string {
  if (net === null) return "hsl(var(--muted-foreground) / 0.3)";
  if (net > 0.1) return "hsl(142 70% 45%)";
  if (net < -0.1) return "hsl(0 80% 55%)";
  return "hsl(220 15% 50%)";
}

function pctColor(pct: number | null): string {
  if (pct === null) return "text-muted-foreground";
  return pct >= 0 ? "text-emerald-400" : "text-red-400";
}

function fmtPct(pct: number): string {
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

type CalendarViewProps = {
  onSelectDate: (dateIso: string) => void;
  selectedDate: string | null;
  onQueueDate: (dateIso: string) => void;
  onRemoveFromQueue: (dateIso: string) => void;
  queue: string[];
  running: boolean;
  runningDate: string;
  portfolioTickers: string[];
  quantities: Record<string, number>;
};

export function CalendarView({
  onSelectDate,
  selectedDate,
  onQueueDate,
  onRemoveFromQueue,
  queue,
  running,
  runningDate,
  portfolioTickers,
  quantities,
}: CalendarViewProps) {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);

  const monthKey = toMonthKey(year, month);
  const hasPortfolio = portfolioTickers.length > 0;
  const { data, loading } = useCalendar(
    monthKey,
    hasPortfolio ? { tickers: portfolioTickers, quantities } : undefined,
  );

  const dayMap = new Map<string, CalendarDay>(
    (data?.days ?? []).map((d) => [d.date, d]),
  );

  const firstDay = new Date(year, month - 1, 1);
  const startOffset = firstDay.getDay();
  const daysInMonth = new Date(year, month, 0).getDate();
  const cells: Array<{ date: string; day: number } | null> = [
    ...Array(startOffset).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => {
      const d = i + 1;
      const date = `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      return { date, day: d };
    }),
  ];
  while (cells.length % 7 !== 0) cells.push(null);

  const numRows = cells.length / 7;

  function prevMonth() {
    if (month === 1) { setMonth(12); setYear(y => y - 1); }
    else setMonth(m => m - 1);
  }
  function nextMonth() {
    if (month === 12) { setMonth(1); setYear(y => y + 1); }
    else setMonth(m => m + 1);
  }

  return (
    <div className="h-full flex flex-col px-8 py-5 gap-3">
      {/* Header */}
      <div className="flex items-center justify-between shrink-0">
        <div>
          <h2 className="font-mono uppercase tracking-[0.25em] text-xs text-muted-foreground mb-1">
            Calendário
          </h2>
          <p className="text-2xl font-semibold">
            {MONTH_NAMES[month - 1]} {year}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={prevMonth} className="p-2 rounded hover:bg-muted/40 transition-colors" aria-label="Mês anterior">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button onClick={nextMonth} className="p-2 rounded hover:bg-muted/40 transition-colors" aria-label="Próximo mês">
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Grid */}
      <div
        className="flex-1 min-h-0 grid grid-cols-7 gap-px"
        style={{ gridTemplateRows: `auto repeat(${numRows}, 1fr)` }}
      >
        {/* Weekday headers */}
        {WEEKDAYS.map((d, i) => {
          const isWknd = i === 0 || i === 6;
          return (
            <div
              key={d}
              style={{ backgroundImage: isWknd ? WEEKEND_HATCH : undefined }}
              className={[
                "text-center text-[10px] font-mono uppercase tracking-widest py-1.5 border-b",
                isWknd
                  ? "text-muted-foreground/25 border-border/20"
                  : "text-primary/50 border-primary/20",
              ].join(" ")}
            >
              {d}
            </div>
          );
        })}

        {/* Day cells */}
        {loading
          ? Array.from({ length: numRows * 7 }).map((_, i) => (
              <div key={i} className="bg-muted/20 animate-pulse" />
            ))
          : cells.map((cell, i) => {
              if (!cell) {
                const isWknd = i % 7 === 0 || i % 7 === 6;
                return (
                  <div
                    key={i}
                    style={{ backgroundImage: isWknd ? WEEKEND_HATCH : undefined }}
                    className={isWknd ? "border border-border/10" : ""}
                  />
                );
              }

              const info = dayMap.get(cell.date);
              const isSelected = cell.date === selectedDate;
              const hasData = info?.has_articles ?? false;
              const isWeekend = i % 7 === 0 || i % 7 === 6;
              const isRunning = running && runningDate === cell.date;
              const isQueued = queue.includes(cell.date);

              return (
                <div
                  key={cell.date}
                  style={{ backgroundImage: isWeekend ? WEEKEND_HATCH : WEEKDAY_GRADIENT }}
                  className={[
                    "px-1.5 py-1.5 flex flex-col gap-0.5 transition-colors relative group min-h-0 cursor-pointer overflow-hidden",
                    isWeekend
                      ? "border border-border/15 hover:border-border/40 hover:bg-muted/10"
                      : "border border-primary/10 hover:border-primary/30 hover:bg-primary/5",
                    isSelected ? "ring-1 ring-inset ring-primary border-primary/40" : "",
                  ].join(" ")}
                  onClick={() => onSelectDate(cell.date)}
                >
                  {/* Top row: day number + queue button */}
                  <div className="flex items-center justify-between">
                    <span
                      className={`text-sm font-mono font-bold leading-none ${
                        isSelected
                          ? "text-primary"
                          : isWeekend
                            ? "text-muted-foreground/35"
                            : "text-foreground"
                      }`}
                    >
                      {cell.day}
                    </span>

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (!isRunning) onQueueDate(cell.date);
                      }}
                      disabled={isRunning}
                      title={isRunning ? "Executando…" : isQueued ? "Remover da fila" : "Adicionar à fila"}
                      className={[
                        "p-0.5 rounded transition-opacity",
                        isRunning || isQueued ? "opacity-100" : "opacity-0 group-hover:opacity-100",
                        isRunning ? "cursor-not-allowed" : isQueued ? "hover:text-destructive" : "hover:text-primary",
                      ].join(" ")}
                      aria-label={`Pipeline para ${cell.date}`}
                    >
                      {isRunning ? (
                        <Loader2 className="h-3 w-3 text-primary animate-spin" />
                      ) : isQueued ? (
                        <ListOrdered className="h-3 w-3 text-primary/70" />
                      ) : (
                        <PlayCircle className={`h-3 w-3 ${isWeekend ? "text-foreground/50" : "text-muted-foreground"}`} />
                      )}
                    </button>
                  </div>

                  {/* Data rows */}
                  <div className="flex flex-col gap-px w-full min-w-0">
                    {hasData && info ? (
                      <>
                        <div className="flex items-baseline justify-between gap-1 min-w-0">
                          <span className="text-[9px] font-mono text-muted-foreground/50 uppercase tracking-wide shrink-0">art</span>
                          <div className="flex items-center gap-0.5 min-w-0">
                            <span
                              className="w-1 h-1 rounded-full shrink-0"
                              style={{ background: sentimentColor(info.sentiment_net) }}
                            />
                            <span className="text-[10px] font-mono font-medium text-foreground/80 truncate">{info.article_count}</span>
                          </div>
                        </div>

                        {info.positive_pct !== null && info.negative_pct !== null && (
                          <div className="flex items-baseline justify-between gap-1 min-w-0">
                            <span className="text-[9px] font-mono text-muted-foreground/50 uppercase tracking-wide shrink-0">sent</span>
                            <div className="flex items-center gap-0.5 min-w-0">
                              <span className="text-[10px] font-mono text-emerald-400 tabular-nums">{info.positive_pct.toFixed(0)}▲</span>
                              <span className="text-[10px] font-mono text-red-400 tabular-nums">{info.negative_pct.toFixed(0)}▼</span>
                            </div>
                          </div>
                        )}
                      </>
                    ) : !isWeekend ? (
                      <span className="text-[9px] font-mono text-muted-foreground/25">sem dados</span>
                    ) : null}

                    {info?.ibovespa_change_pct !== null && info?.ibovespa_change_pct !== undefined && (
                      <div className="flex items-baseline justify-between gap-1 min-w-0">
                        <span className="text-[9px] font-mono text-muted-foreground/50 uppercase tracking-wide shrink-0">ibov</span>
                        <span className={`text-[10px] font-mono font-medium tabular-nums truncate ${pctColor(info.ibovespa_change_pct)}`}>
                          {fmtPct(info.ibovespa_change_pct)}
                        </span>
                      </div>
                    )}

                    {hasPortfolio && info?.portfolio_change_pct !== null && info?.portfolio_change_pct !== undefined && (
                      <div className="flex items-baseline justify-between gap-1 min-w-0">
                        <span className="text-[9px] font-mono text-muted-foreground/50 uppercase tracking-wide shrink-0">cart</span>
                        <span className={`text-[10px] font-mono font-medium tabular-nums truncate ${pctColor(info.portfolio_change_pct)}`}>
                          {fmtPct(info.portfolio_change_pct)}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
      </div>

      {/* Legend + queue */}
      <div className="shrink-0 flex flex-col gap-2">
        <div className="flex items-center gap-4 pt-1 border-t border-border/40">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500/80" />
            <span className="text-[10px] font-mono text-muted-foreground/60 uppercase tracking-wider">Positivo</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-slate-500/60" />
            <span className="text-[10px] font-mono text-muted-foreground/60 uppercase tracking-wider">Neutro</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-red-500/80" />
            <span className="text-[10px] font-mono text-muted-foreground/60 uppercase tracking-wider">Negativo</span>
          </div>
        </div>

        {(running || queue.length > 0) && (
          <div className="border-t border-border/40 pt-2">
            <div className="flex items-center gap-2 mb-1.5">
              <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/60">
                Fila de processamento
              </span>
              {queue.length > 0 && (
                <span className="text-[10px] font-mono text-primary/70">({queue.length})</span>
              )}
            </div>
            <div className="flex items-center gap-2 overflow-x-auto pb-1">
              {running && (
                <div className="shrink-0 flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-primary/40 bg-primary/5 text-primary text-[11px] font-mono">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  <span>{runningDate}</span>
                </div>
              )}
              {queue.map((date) => (
                <div
                  key={date}
                  className="shrink-0 flex items-center gap-1 px-2.5 py-1 rounded-full border border-border/60 bg-muted/20 text-[11px] font-mono text-muted-foreground"
                >
                  <span>{date}</span>
                  <button
                    onClick={() => onRemoveFromQueue(date)}
                    className="ml-0.5 hover:text-destructive transition-colors"
                    aria-label={`Remover ${date} da fila`}
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
