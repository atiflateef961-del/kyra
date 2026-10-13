import type { HTMLAttributes, ReactNode } from "react";

import { cx } from "./surface-utils";

export type LiquidPanelProps = HTMLAttributes<HTMLElement> & {
  children: ReactNode;
  accent?: "blue" | "aqua" | "green";
  as?: "article" | "section" | "div";
};

export function LiquidPanel({
  as: Element = "section",
  children,
  className,
  accent = "blue",
  ...props
}: LiquidPanelProps) {
  return (
    <Element className={cx("kyra-liquid-panel", `kyra-liquid-panel--${accent}`, className)} {...props}>
      {children}
    </Element>
  );
}
