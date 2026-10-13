# Motion primitives

These components use Motion for React (`motion/react`). Install the frontend
runtime before importing them into an application.

- `MotionProvider` applies the user's reduced-motion preference globally.
- `PageTransition` provides entry/exit navigation motion.
- `PressMotion` decorates an existing native control; it never replaces it.
- `ModalTransition` provides only backdrop/panel presence animation. A later
  accessible dialog primitive must own focus trapping and dialog semantics.
- `StateTransition` visualizes a supplied `idle`, `active`, `success`, `error`,
  or `offline` state; it does not create status data.
