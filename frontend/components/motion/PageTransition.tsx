import type { HTMLMotionProps } from "motion/react";
import { motion } from "motion/react";

import { kyraPageVariants } from "../../lib/motion";

export type PageTransitionProps = HTMLMotionProps<"main">;

export function PageTransition({ children, ...props }: PageTransitionProps) {
  return (
    <motion.main {...props} initial="initial" animate="animate" exit="exit" variants={kyraPageVariants}>
      {children}
    </motion.main>
  );
}
