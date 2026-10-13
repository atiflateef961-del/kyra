import type { ReactNode } from "react";
import type { HTMLMotionProps } from "motion/react";
import { motion } from "motion/react";

import { kyraPressTransition } from "../../lib/motion";
import { cx } from "./surface-utils";

export type NeumorphicButtonProps = Omit<HTMLMotionProps<"button">, "children"> & {
  children: ReactNode;
  tone?: "primary" | "neutral" | "danger";
  size?: "sm" | "md" | "lg";
};

export function NeumorphicButton({
  children,
  className,
  size = "md",
  tone = "neutral",
  type = "button",
  ...props
}: NeumorphicButtonProps) {
  return (
    <motion.button
      className={cx("kyra-neumorphic-button", `kyra-neumorphic-button--${tone}`, `kyra-neumorphic-button--${size}`, className)}
      type={type}
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.98, y: 0 }}
      transition={kyraPressTransition}
      {...props}
    >
      {children}
    </motion.button>
  );
}
