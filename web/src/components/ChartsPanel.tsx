import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

const SLOTS: { id: string; label: string }[] = [
  { id: "sentiment", label: "Sentimento" },
  { id: "volume", label: "Volume" },
  { id: "sectors", label: "Setores" },
  { id: "conflicts", label: "Conflitos" },
];

export type ChartsPanelProps = {
  date: string | null;
};

export function ChartsPanel({ date }: ChartsPanelProps) {
  if (!date) {
    return (
      <Card className="flex items-center justify-center py-16">
        <p className="text-muted-foreground">
          Selecione uma data para visualizar os gráficos.
        </p>
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {SLOTS.map((slot) => (
        <Card key={slot.id}>
          <CardHeader className="pb-2 flex flex-row items-center justify-between">
            <CardTitle className="text-base font-mono uppercase tracking-widest">
              {slot.label}
            </CardTitle>
            <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70">
              em construção
            </span>
          </CardHeader>
          <CardContent>
            <div className="h-48 rounded-md bg-muted/40 border border-border/60 animate-pulse" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
