import * as React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
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
    <Card className={cn("border-border/60", className)}>
      <CardHeader className="pb-2 flex flex-row items-center justify-between">
        <CardTitle className="text-base font-mono uppercase tracking-widest">
          {title}
        </CardTitle>
        {subtitle ? (
          <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/70">
            {subtitle}
          </span>
        ) : null}
      </CardHeader>
      <div className="scanline h-px w-full" />
      <CardContent className={cn("pt-4", contentClassName)}>{children}</CardContent>
    </Card>
  );
}
