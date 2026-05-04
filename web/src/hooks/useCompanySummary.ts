import { useEffect, useState } from "react";
import { getCompanySummary, type CompanySummary } from "../api";

export type UseCompanySummaryState = {
  data: CompanySummary | null;
  loading: boolean;
  error: Error | null;
};

export function useCompanySummary(
  ticker: string | null,
  date: string | null,
): UseCompanySummaryState {
  const [state, setState] = useState<UseCompanySummaryState>({
    data: null,
    loading: false,
    error: null,
  });

  useEffect(() => {
    if (!ticker || !date) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    const ctrl = new AbortController();
    setState({ data: null, loading: true, error: null });
    getCompanySummary(ticker, date, ctrl.signal)
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
  }, [ticker, date]);

  return state;
}
