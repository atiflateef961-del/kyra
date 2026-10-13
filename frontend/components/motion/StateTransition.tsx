import type { HTMLMotionProps } from "motion/react";
import { motion } from "motion/react";

import { kyraStatusVariants, type KyraStatusMotion } from "../../lib/motion";

export type StateTransitionProps = HTMLMotionProps<"div"> & {
  state: KyraStatusMotion;
};

/** A presentational state animator; it receives state and never invents it. */
export function StateTransition({ children, state, ...props }: StateTransitionProps) {
  return (
    <motion.div {...props} animate={state} initial={false} variants={kyraStatusVariants}>
      {children}
    </motion.div>
  );
}
