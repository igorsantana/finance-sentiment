import * as React from "react";
import { Pane, cn } from "@cyberdeck/ui";

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
    <Pane
      className={cn("border-0 bg-transparent shadow-none", className)}
      contentClassName={cn("border-t border-border/40 pt-4", contentClassName)}
      header={
        <div className="flex items-center justify-between">
          <span className="text-xs font-mono uppercase tracking-widest text-foreground/70">
            {title}
          </span>
          {subtitle ? (
            <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/60">
              {subtitle}
            </span>
          ) : null}
        </div>
      }
    >
      {children}
    </Pane>
  );
}
