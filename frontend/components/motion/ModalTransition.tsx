import type { ReactNode } from "react";
import type { HTMLMotionProps } from "motion/react";
import { AnimatePresence, motion } from "motion/react";

import { kyraBackdropVariants, kyraModalVariants } from "../../lib/motion";

export type ModalTransitionProps = {
  children: ReactNode;
  isOpen: boolean;
  onBackdropClick?: () => void;
  backdropProps?: Omit<HTMLMotionProps<"div">, "children" | "onClick">;
  panelProps?: Omit<HTMLMotionProps<"div">, "children" | "onClick">;
};

/**
 * Transition-only shell. Callers must provide the dialog's focus management,
 * semantics, and dismissal policy (for example through a later Radix dialog).
 */
export function ModalTransition({ children, isOpen, onBackdropClick, backdropProps, panelProps }: ModalTransitionProps) {
  return (
    <AnimatePresence>
      {isOpen ? (
        <motion.div
          {...backdropProps}
          aria-hidden="true"
          initial="initial"
          animate="animate"
          exit="exit"
          variants={kyraBackdropVariants}
          onClick={onBackdropClick}
        >
          <motion.div
            {...panelProps}
            initial="initial"
            animate="animate"
            exit="exit"
            variants={kyraModalVariants}
            onClick={(event) => event.stopPropagation()}
          >
            {children}
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
