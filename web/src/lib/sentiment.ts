export type SentimentTone = "positive" | "neutral" | "negative";

export const SENTIMENT_COLORS: Record<SentimentTone, string> = {
  positive: "hsl(var(--sentiment-positive))",
  neutral: "hsl(var(--sentiment-neutral))",
  negative: "hsl(var(--sentiment-negative))",
};

export const SENTIMENT_LABEL_PT: Record<SentimentTone, string> = {
  positive: "Positivo",
  neutral: "Neutro",
  negative: "Negativo",
};

export function netTone(positive: number, negative: number): SentimentTone {
  if (positive > negative) return "positive";
  if (negative > positive) return "negative";
  return "neutral";
}
