import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

export type ComboboxOption = {
  value: string;
  label: string;
  hint?: string;
};

export type ComboboxProps = {
  value: string | null;
  options: ComboboxOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  emptyLabel?: string;
};

export function Combobox({
  value,
  options,
  onChange,
  placeholder = "Buscar…",
  emptyLabel = "— sem resultados —",
}: ComboboxProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const selected = useMemo(
    () => options.find((o) => o.value === value) ?? null,
    [options, value],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter(
      (o) =>
        o.value.toLowerCase().includes(q) ||
        o.label.toLowerCase().includes(q),
    );
  }, [options, query]);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  useEffect(() => {
    setActiveIdx(0);
  }, [query, open]);

  useEffect(() => {
    if (!open) return;
    const el = listRef.current?.querySelector<HTMLElement>(
      `[data-idx="${activeIdx}"]`,
    );
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIdx, open]);

  const commit = (val: string) => {
    onChange(val);
    setOpen(false);
    setQuery("");
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActiveIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const opt = filtered[activeIdx];
      if (opt) commit(opt.value);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
  };

  return (
    <div ref={wrapRef} className="relative w-full max-w-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-md border border-border bg-muted/30 text-sm font-mono hover:bg-muted/50 transition-colors"
      >
        <span className="truncate text-left">
          {selected ? (
            <>
              <span className="text-primary">{selected.value}</span>
              {selected.label !== selected.value && (
                <span className="text-muted-foreground"> · {selected.label}</span>
              )}
            </>
          ) : (
            <span className="text-muted-foreground">{placeholder}</span>
          )}
        </span>
        <ChevronDown
          className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && (
        <div className="absolute z-20 mt-1 w-full rounded-md border border-border bg-background shadow-none neon-edge">
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={placeholder}
            className="w-full px-3 py-2 bg-transparent border-b border-border text-sm font-mono outline-none focus:border-primary/60"
          />
          <div ref={listRef} className="max-h-72 overflow-auto py-1">
            {filtered.length === 0 ? (
              <div className="px-3 py-2 text-xs font-mono text-muted-foreground/70">
                {emptyLabel}
              </div>
            ) : (
              filtered.map((opt, idx) => {
                const active = idx === activeIdx;
                const isSelected = opt.value === value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    data-idx={idx}
                    onMouseEnter={() => setActiveIdx(idx)}
                    onClick={() => commit(opt.value)}
                    className={`w-full flex items-center justify-between gap-3 px-3 py-1.5 text-left text-sm font-mono transition-colors ${
                      active
                        ? "bg-primary/10 text-primary"
                        : "text-foreground hover:bg-muted/40"
                    }`}
                  >
                    <span className="flex items-center gap-2 min-w-0">
                      <span
                        className={`text-[10px] uppercase tracking-widest ${
                          isSelected ? "text-primary" : "text-primary/60"
                        }`}
                      >
                        {isSelected ? "▸" : "·"}
                      </span>
                      <span className="text-primary">{opt.value}</span>
                      {opt.label !== opt.value && (
                        <span className="text-muted-foreground truncate">
                          {opt.label}
                        </span>
                      )}
                    </span>
                    {opt.hint && (
                      <span className="text-[10px] text-muted-foreground/70 shrink-0">
                        {opt.hint}
                      </span>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
