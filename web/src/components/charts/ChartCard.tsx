import * as React from "react";
import { cn } from "../../lib/utils";

export type ChartCardProps = {
  title: string;
  subtitle?: React.ReactNode;
  className?: string;
  contentClassName?: string;
  children: React.ReactNode;
};

export function ChartCard({
  title,
  subtitle,
  className,
  contentClassName,
  children,
}: ChartCardProps) {
  return (
    <div className={cn("", className)}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-mono uppercase tracking-widest text-foreground/70">
          {title}
        </span>
        {subtitle ? (
          <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/60">
            {subtitle}
          </span>
        ) : null}
      </div>
      <div className="border-b border-border/40 mb-4" />
      <div className={cn("", contentClassName)}>{children}</div>
    </div>
  );
}
