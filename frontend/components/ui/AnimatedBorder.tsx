import type { HTMLAttributes, ReactNode } from "react";

import { cx } from "./surface-utils";

export type AnimatedBorderProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  tone?: "blue" | "aqua" | "green" | "rose" | "success";
};

/**
 * A decorative wrapper. It does not add a role or change the semantics of the
 * child content; callers should supply semantic markup inside it.
 */
export function AnimatedBorder({ children, className, tone = "blue", ...props }: AnimatedBorderProps) {
  return (
    <div className={cx("kyra-animated-border", `kyra-animated-border--${tone}`, className)} {...props}>
      <div className="kyra-animated-border__content">{children}</div>
    </div>
  );
}
