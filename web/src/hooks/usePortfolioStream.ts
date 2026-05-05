import { useEffect, useRef, useState } from "react";
import type { PortfolioPriceItem } from "../api";

export type PortfolioPrices = Record<string, PortfolioPriceItem>;

export function usePortfolioStream(tickers: string[]): {
  prices: PortfolioPrices;
  connected: boolean;
} {
  const [prices, setPrices] = useState<PortfolioPrices>({});
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    setPrices({});
    setConnected(false);

    if (tickers.length === 0) return;

    const qs = new URLSearchParams({ tickers: tickers.join(",") });
    const es = new EventSource(`/api/portfolio/stream?${qs}`);
    esRef.current = es;

    es.onopen = () => setConnected(true);

    es.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data) as {
          type: "prices";
          items: PortfolioPriceItem[];
        };
        if (msg.type === "prices") {
          setPrices(
            Object.fromEntries(msg.items.map((item) => [item.tickerRoot, item]))
          );
        }
      } catch {
        // ignore malformed events
      }
    };

    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        setConnected(false);
      }
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [tickers.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  return { prices, connected };
}
