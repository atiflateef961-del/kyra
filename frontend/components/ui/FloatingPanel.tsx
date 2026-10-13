import type { HTMLAttributes, ReactNode } from "react";

import { cx } from "./surface-utils";

export type FloatingPanelProps = HTMLAttributes<HTMLElement> & {
  children: ReactNode;
  placement?: "top-right" | "bottom-right" | "bottom-left" | "top-left";
};

export function FloatingPanel({
  children,
  className,
  placement = "bottom-right",
  ...props
}: FloatingPanelProps) {
  return (
    <aside className={cx("kyra-floating-panel", `kyra-floating-panel--${placement}`, className)} {...props}>
      {children}
    </aside>
  );
}
