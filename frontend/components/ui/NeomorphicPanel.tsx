import type { HTMLAttributes, ReactNode } from "react";

import { cx } from "./surface-utils";

export type NeomorphicPanelProps = HTMLAttributes<HTMLElement> & {
  children: ReactNode;
  as?: "article" | "section" | "div";
  pressed?: boolean;
};

export function NeomorphicPanel({
  as: Element = "section",
  children,
  className,
  pressed = false,
  ...props
}: NeomorphicPanelProps) {
  return (
    <Element
      className={cx("kyra-neomorphic-panel", pressed && "kyra-neomorphic-panel--pressed", className)}
      {...props}
    >
      {children}
    </Element>
  );
}
