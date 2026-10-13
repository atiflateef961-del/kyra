import type { HTMLMotionProps } from "motion/react";
import { motion } from "motion/react";

import { kyraPressTransition } from "../../lib/motion";

export type PressMotionProps = HTMLMotionProps<"div">;

/**
 * Decorative interaction wrapper for a native control supplied as children.
 * It does not replace native button, link, focus, or keyboard behavior.
 */
export function PressMotion({ children, ...props }: PressMotionProps) {
  return <motion.div {...props} whileHover={{ y: -2 }} whileTap={{ scale: 0.98, y: 0 }} transition={kyraPressTransition}>{children}</motion.div>;
}
