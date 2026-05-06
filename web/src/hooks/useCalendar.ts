import { useEffect, useState } from "react";
import { getCalendar, type CalendarPayload } from "../api";

export type UseCalendarState = {
  data: CalendarPayload | null;
  loading: boolean;
  error: Error | null;
};

export function useCalendar(
  month: string,
  portfolio?: { tickers: string[]; quantities: Record<string, number> },
): UseCalendarState {
  const [state, setState] = useState<UseCalendarState>({
    data: null,
    loading: false,
    error: null,
  });

  // Serialize portfolio so the effect re-runs when it changes
  const portfolioKey = portfolio
    ? portfolio.tickers.sort().map((t) => `${t}:${portfolio.quantities[t] ?? 1}`).join(",")
    : "";

  useEffect(() => {
    if (!month) return;
    const ctrl = new AbortController();
    setState({ data: null, loading: true, error: null });
    getCalendar(month, {
      tickers: portfolio?.tickers,
      quantities: portfolio?.quantities,
      signal: ctrl.signal,
    })
      .then((data) => {
        if (ctrl.signal.aborted) return;
        setState({ data, loading: false, error: null });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setState({
          data: null,
          loading: false,
          error: err instanceof Error ? err : new Error(String(err)),
        });
      });
    return () => ctrl.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [month, portfolioKey]);

  return state;
}
