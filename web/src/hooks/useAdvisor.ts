import { useEffect, useState } from "react";
import {
  getAdvisor,
  type AdvisorNarrative,
  type AdvisorScope,
  type WindowSize,
} from "../api";

export type UseAdvisorState = {
  data: AdvisorNarrative | null;
  loading: boolean;
  error: Error | null;
  unavailable: boolean;
};

function scopeKey(scope: AdvisorScope): string {
  return scope === "overall" ? "overall" : `c:${scope.ticker}`;
}

export function useAdvisor(
  scope: AdvisorScope,
  window: WindowSize,
  end?: string,
  tickers?: string[],
): UseAdvisorState {
  const [state, setState] = useState<UseAdvisorState>({
    data: null,
    loading: false,
    error: null,
    unavailable: false,
  });

  const key = scopeKey(scope);
  const tickersKey = tickers?.join(",") ?? "";

  useEffect(() => {
    const ctrl = new AbortController();
    setState({ data: null, loading: true, error: null, unavailable: false });
    getAdvisor(scope, window, end, ctrl.signal, tickers?.length ? tickers : undefined)
      .then((data) => {
        if (ctrl.signal.aborted) return;
        setState({
          data,
          loading: false,
          error: null,
          unavailable: data === null,
        });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setState({
          data: null,
          loading: false,
          error: err instanceof Error ? err : new Error(String(err)),
          unavailable: false,
        });
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, window, end, tickersKey]);

  return state;
}
