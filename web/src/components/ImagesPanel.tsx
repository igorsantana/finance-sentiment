import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

export type ImagesPanelProps = {
  date: string | null;
  processed: boolean;
  hasArticles: boolean;
  // Cache-buster appended as ?v=… so a fresh run replaces the browser-cached PNG.
  imageBust: string;
};

export function ImagesPanel({ date, processed, hasArticles, imageBust }: ImagesPanelProps) {
  const [hidden, setHidden] = useState<{ dashboard: boolean; report: boolean }>({
    dashboard: false,
    report: false,
  });

  // Reset onError flags when the date or cache-bust changes.
  useEffect(() => {
    setHidden({ dashboard: false, report: false });
  }, [date, imageBust]);

  const showImages = !!date && processed;
  const src = (kind: "dashboard" | "report") =>
    `/data/images/${date}/${kind}.png${imageBust ? `?v=${imageBust}` : ""}`;

  if (!showImages || (hidden.dashboard && hidden.report)) {
    return (
      <Card className="flex items-center justify-center py-16">
        <div className="text-center">
          <div className="text-4xl mb-2">📊</div>
          <p className="text-muted-foreground">
            {date && hasArticles && !processed
              ? "Esta data tem artigos, mas ainda não foi processada."
              : "Selecione uma data processada para visualizar os resultados."}
          </p>
        </div>
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {!hidden.dashboard && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-mono uppercase tracking-widest">
              Dashboard
            </CardTitle>
          </CardHeader>
          <CardContent>
            <img
              src={src("dashboard")}
              alt="Dashboard"
              className="w-full rounded border border-border"
              onError={() => setHidden((s) => ({ ...s, dashboard: true }))}
            />
          </CardContent>
        </Card>
      )}
      {!hidden.report && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-mono uppercase tracking-widest">
              Relatório
            </CardTitle>
          </CardHeader>
          <CardContent>
            <img
              src={src("report")}
              alt="Report"
              className="w-full rounded border border-border"
              onError={() => setHidden((s) => ({ ...s, report: true }))}
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
