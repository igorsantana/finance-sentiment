import { ChartCard } from "../charts/ChartCard";
import { HeaderStats } from "../charts/HeaderStats";
import { SentimentDonut } from "../charts/SentimentDonut";
import { TopCompaniesBar } from "../charts/TopCompaniesBar";
import { SentimentByPublisher } from "../charts/SentimentByPublisher";
import { CompaniesStacked } from "../charts/CompaniesStacked";
import { SectorHeatmap } from "../charts/SectorHeatmap";
import { SectorDrilldown } from "../charts/SectorDrilldown";
import { HourlyTimeline } from "../charts/HourlyTimeline";
import { ScoreHistogram } from "../charts/ScoreHistogram";
import { TopSubjects } from "../charts/TopSubjects";
import { TopTickers } from "../charts/TopTickers";
import { Currencies } from "../charts/Currencies";
import { useReport } from "../../hooks/useReport";
import type { ReportPayload } from "../../api";

type SlotId =
  | "D1" | "D2" | "D3" | "D5"
  | "R2" | "R3" | "R4"
  | "X1" | "X4" | "X5" | "X6" | "X7";

type Slot = { id: SlotId; title: string };

export type ChartsPanelProps = {
  date: string | null;
};

function Skeleton() {
  return (
    <div className="h-48 rounded-md bg-muted/40 border border-border/60 animate-pulse" />
  );
}

function SlotCard({ slot }: { slot: Slot }) {
  return (
    <ChartCard title={slot.title} subtitle="carregando…">
      <Skeleton />
    </ChartCard>
  );
}

export function ChartsPanel({ date }: ChartsPanelProps) {
  const { data, loading, error } = useReport(date);

  if (!date) {
    return (
      <div className="flex items-center justify-center py-16">
        <p className="text-muted-foreground">
          Selecione uma data processada para visualizar os gráficos.
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-10 text-center space-y-2">
        <p className="font-mono uppercase tracking-widest text-sm text-accent">
          falha ao carregar relatório
        </p>
        <p className="text-xs text-muted-foreground font-mono">{error.message}</p>
      </div>
    );
  }

  if (!loading && data === null) {
    return (
      <div className="flex items-center justify-center py-16">
        <p className="text-muted-foreground">
          Selecione uma data processada para visualizar os gráficos.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <ResumoSection data={data} />
      <DetalhesSection data={data} />
      <InsightsSection data={data} />
    </div>
  );
}

function ResumoSection({ data }: { data: ReportPayload | null }) {
  return (
    <section className="space-y-3">
      <h2 className="text-xs font-mono uppercase tracking-[0.2em] text-muted-foreground/80">
        Resumo
      </h2>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        {data ? (
          <>
            <HeaderStats data={data} />
            <SentimentDonut data={data} />
            <TopCompaniesBar data={data} />
            <SentimentByPublisher data={data} />
          </>
        ) : (
          <>
            <SlotCard slot={{ id: "D1", title: "Resumo" }} />
            <SlotCard slot={{ id: "D2", title: "Distribuição de sentimento" }} />
            <SlotCard slot={{ id: "D3", title: "Top empresas (12)" }} />
            <SlotCard slot={{ id: "D5", title: "Sentimento por veículo (25)" }} />
          </>
        )}
      </div>
    </section>
  );
}

function DetalhesSection({ data }: { data: ReportPayload | null }) {
  return (
    <section className="space-y-3">
      <h2 className="text-xs font-mono uppercase tracking-[0.2em] text-muted-foreground/80">
        Detalhes por empresa &amp; setor
      </h2>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        {data ? (
          <>
            <CompaniesStacked data={data} />
            <SectorDrilldown data={data} />
          </>
        ) : (
          <>
            <SlotCard slot={{ id: "R2", title: "Empresas — empilhado (20)" }} />
            <SlotCard slot={{ id: "R4", title: "Setores com empresas-chave" }} />
          </>
        )}
      </div>
    </section>
  );
}

function InsightsSection({ data }: { data: ReportPayload | null }) {
  return (
    <section className="space-y-3">
      <h2 className="text-xs font-mono uppercase tracking-[0.2em] text-muted-foreground/80">
        Insights
      </h2>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        {data ? (
          <>
            <SectorHeatmap data={data} />
            <HourlyTimeline data={data} />
            <ScoreHistogram data={data} />
            <TopSubjects data={data} />
            <TopTickers data={data} />
            <Currencies data={data} />
          </>
        ) : (
          <>
            <SlotCard slot={{ id: "R3", title: "Mapa de calor — setores" }} />
            <SlotCard slot={{ id: "X1", title: "Linha do tempo (hora)" }} />
            <SlotCard slot={{ id: "X6", title: "Histograma de score" }} />
            <SlotCard slot={{ id: "X4", title: "Top assuntos" }} />
            <SlotCard slot={{ id: "X5", title: "Top tickers" }} />
            <SlotCard slot={{ id: "X7", title: "Moedas" }} />
          </>
        )}
      </div>
    </section>
  );
}
