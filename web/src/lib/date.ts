// ``YYYY-MM-DD`` → ``DD/MM/YYYY`` (pt-BR display). The wire format stays ISO
// because URLs, sets, and DB queries all expect it; this is presentation-only.
export function formatPtBr(iso: string | null | undefined): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  return `${m[3]}/${m[2]}/${m[1]}`;
}
