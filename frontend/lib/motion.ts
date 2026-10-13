import type { Transition, Variants } from "motion/react";

export const kyraTransition = {
  fast: { duration: 0.14, ease: [0.2, 0.8, 0.2, 1] },
  standard: { duration: 0.22, ease: [0.2, 0.8, 0.2, 1] },
  slow: { duration: 0.42, ease: [0.2, 0.8, 0.2, 1] },
} satisfies Record<string, Transition>;

export const kyraPressTransition = {
  duration: 0.14,
  ease: [0.2, 0.8, 0.2, 1],
} satisfies Transition;

export const kyraPageVariants = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0, transition: kyraTransition.standard },
  exit: { opacity: 0, y: -6, transition: kyraTransition.fast },
} satisfies Variants;

export const kyraModalVariants = {
  initial: { opacity: 0, scale: 0.97, y: 8 },
  animate: { opacity: 1, scale: 1, y: 0, transition: kyraTransition.standard },
  exit: { opacity: 0, scale: 0.98, y: 4, transition: kyraTransition.fast },
} satisfies Variants;

export const kyraBackdropVariants = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: kyraTransition.fast },
  exit: { opacity: 0, transition: kyraTransition.fast },
} satisfies Variants;

export const kyraStatusVariants = {
  idle: { opacity: 0.74, scale: 1 },
  listening: { opacity: 1, scale: [1, 1.02, 1], transition: { ...kyraTransition.slow, repeat: Infinity } },
  thinking: { opacity: [0.78, 1, 0.78], backgroundPosition: ["0% 50%", "100% 50%"], transition: { ...kyraTransition.slow, repeat: Infinity, repeatType: "mirror" } },
  executing: { opacity: 1, scale: 1.01, transition: kyraTransition.standard },
  active: { opacity: 1, scale: 1.02, transition: kyraTransition.standard },
  success: { opacity: 1, scale: 1, transition: { ...kyraTransition.fast, type: "spring", stiffness: 340, damping: 20 } },
  error: { opacity: 1, x: [0, -3, 3, 0], transition: { duration: 0.28 } },
  offline: { opacity: 0.55, scale: 1, transition: kyraTransition.fast },
} satisfies Variants;

// spring: sidebar navigation settles into its active position without a hard snap.
export const kyraSidebarItemVariants = {
  rest: { x: 0, opacity: 0.82 },
  hover: { x: 4, opacity: 1, transition: { type: "spring", stiffness: 420, damping: 26 } },
  active: { x: 5, opacity: 1, transition: { type: "spring", stiffness: 360, damping: 24 } },
} satisfies Variants;

// electric-flow: sidebar items enter as a calm, staggered navigation rail.
export const kyraSidebarNavVariants = {
  initial: { opacity: 0, x: -12 },
  animate: { opacity: 1, x: 0, transition: { ...kyraTransition.standard, staggerChildren: 0.045 } },
} satisfies Variants;

export type KyraStatusMotion = keyof typeof kyraStatusVariants;
