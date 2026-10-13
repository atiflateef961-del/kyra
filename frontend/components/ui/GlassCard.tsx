import type { HTMLAttributes, ReactNode } from "react";

import { cx } from "./surface-utils";

export type GlassCardProps = HTMLAttributes<HTMLElement> & {
  children: ReactNode;
  elevation?: "flat" | "raised";
  as?: "article" | "section" | "div";
};

export function GlassCard({
  as: Element = "section",
  children,
  className,
  elevation = "raised",
  ...props
}: GlassCardProps) {
  return (
    <Element className={cx("kyra-glass-card", `kyra-glass-card--${elevation}`, className)} {...props}>
      {children}
    </Element>
  );
}
