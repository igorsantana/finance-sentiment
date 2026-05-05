import { useEffect, useState } from "react";
import { getTrendsCompany, type WindowCompany, type WindowSize } from "../api";

export type UseTrendsCompanyState = {
  data: WindowCompany | null;
  loading: boolean;
  error: Error | null;
};

export function useTrendsCompany(
  ticker: string | null,
  window: WindowSize,
  end?: string,
): UseTrendsCompanyState {
  const [state, setState] = useState<UseTrendsCompanyState>({
    data: null,
    loading: false,
    error: null,
  });

  useEffect(() => {
    if (!ticker) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    const ctrl = new AbortController();
    setState({ data: null, loading: true, error: null });
    getTrendsCompany(ticker, window, end, ctrl.signal)
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
  }, [ticker, window, end]);

  return state;
}
