import { useEffect, useState } from "react";
import { getTrendsOverall, type WindowOverall, type WindowSize } from "../api";

export type UseTrendsOverallState = {
  data: WindowOverall | null;
  loading: boolean;
  error: Error | null;
};

export function useTrendsOverall(
  window: WindowSize,
  end?: string,
  tickers?: string[],
): UseTrendsOverallState {
  const [state, setState] = useState<UseTrendsOverallState>({
    data: null,
    loading: false,
    error: null,
  });

  const tickersKey = tickers?.join(",") ?? "";

  useEffect(() => {
    const ctrl = new AbortController();
    setState({ data: null, loading: true, error: null });
    const tickerList = tickersKey ? tickersKey.split(",") : undefined;
    getTrendsOverall(window, end, ctrl.signal, tickerList)
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
  }, [window, end, tickersKey]); // eslint-disable-line react-hooks/exhaustive-deps

  return state;
}
