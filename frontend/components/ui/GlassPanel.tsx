import type { HTMLAttributes, ReactNode } from "react";

import { cx } from "./surface-utils";

export type GlassPanelProps = HTMLAttributes<HTMLElement> & {
  children: ReactNode;
  tone?: "default" | "muted" | "strong";
  as?: "article" | "section" | "div";
};

export function GlassPanel({
  as: Element = "section",
  children,
  className,
  tone = "default",
  ...props
}: GlassPanelProps) {
  return (
    <Element className={cx("kyra-glass-panel", `kyra-glass-panel--${tone}`, className)} {...props}>
      {children}
    </Element>
  );
}
