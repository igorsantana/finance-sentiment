import { useEffect, useState } from "react";
import { getSentimentSeries, type SentimentSeries } from "../api";

export type UseSentimentSeriesState = {
  data: SentimentSeries | null;
  loading: boolean;
  error: Error | null;
};

export function useSentimentSeries(
  ticker: string | null,
  date: string | null,
): UseSentimentSeriesState {
  const [state, setState] = useState<UseSentimentSeriesState>({
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
    getSentimentSeries(ticker, date, ctrl.signal)
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
