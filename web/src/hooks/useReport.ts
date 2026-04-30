import { useEffect, useState } from "react";
import { getReport, type ReportPayload } from "../api";

export type UseReportState = {
  data: ReportPayload | null;
  loading: boolean;
  error: Error | null;
};

export function useReport(date: string | null): UseReportState {
  const [state, setState] = useState<UseReportState>({
    data: null,
    loading: false,
    error: null,
  });

  useEffect(() => {
    if (!date) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    const ctrl = new AbortController();
    setState({ data: null, loading: true, error: null });
    getReport(date, ctrl.signal)
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
  }, [date]);

  return state;
}
