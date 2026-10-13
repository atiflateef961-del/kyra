import { motion } from "motion/react";
import { useState } from "react";

import { kyraSidebarItemVariants, kyraSidebarNavVariants } from "../../lib/motion";
import type { AgentSocketStatus } from "../../lib/websocket";
import { cx } from "../ui/surface-utils";

type SidebarItem = {
  label: string;
  target: string;
  mark: string;
};

type SidebarProps = {
  status: AgentSocketStatus;
};

const items: SidebarItem[] = [
  { label: "Overview", target: ".kyra-dashboard__hero", mark: "◆" },
  { label: "Vision", target: ".kyra-dashboard__sensor--camera", mark: "◉" },
  { label: "Gestures", target: ".kyra-gesture-studio", mark: "✦" },
  { label: "Voice", target: ".kyra-voice-control", mark: "◌" },
  { label: "Activity", target: ".kyra-dashboard__activity", mark: "≋" },
  { label: "Devices", target: ".kyra-device-panel", mark: "◇" },
  { label: "Settings", target: ".kyra-settings-panel", mark: "⚙" },
];

export function Sidebar({ status }: SidebarProps) {
  const [activeTarget, setActiveTarget] = useState(items[0].target);
  const statusLabel = {
    idle: "Offline",
    connecting: "Connecting",
    open: "Connected",
    reconnecting: "Reconnecting",
    authentication_error: "Authentication error",
    backend_error: "Backend error",
    network_error: "Network error",
    unauthenticated: "Sign in required",
    closed: "Offline",
  }[status];

  function navigate(target: string) {
    setActiveTarget(target);
    document.querySelector(target)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <aside className="kyra-sidebar" aria-label="Kyra navigation">
      <div className="kyra-sidebar__brand">
        <span className="kyra-sidebar__mark" aria-hidden="true">K</span>
        <span>KYRA</span>
      </div>
      <p className="kyra-sidebar__caption">Local intelligence console</p>
      <motion.nav className="kyra-sidebar__nav" initial="initial" animate="animate" variants={kyraSidebarNavVariants}>
        {items.map((item) => (
          <motion.button
            aria-label={`Go to ${item.label}`}
            aria-current={activeTarget === item.target ? "page" : undefined}
            className={cx("kyra-neumorphic-button", "kyra-neumorphic-button--sm", "kyra-sidebar__item", activeTarget === item.target && "kyra-sidebar__item--active")}
            key={item.label}
            onClick={() => navigate(item.target)}
            type="button"
            animate={activeTarget === item.target ? "active" : "rest"}
            variants={kyraSidebarItemVariants}
            whileHover="hover"
            whileTap={{ scale: 0.98 }}
          >
            <span className="kyra-sidebar__item-mark" aria-hidden="true">{item.mark}</span>
            <span>{item.label}</span>
          </motion.button>
        ))}
      </motion.nav>
      <div className="kyra-sidebar__status" aria-label={`Agent connection: ${statusLabel}`} aria-live="polite">
        <span className={`kyra-sidebar__status-dot kyra-sidebar__status-dot--${status}`} aria-hidden="true" />
        <span>{statusLabel}</span>
      </div>
    </aside>
  );
}
