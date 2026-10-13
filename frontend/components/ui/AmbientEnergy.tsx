import { useEffect, useState } from "react";

import type { AgentState } from "../../types/contracts";
import type { AgentSocketStatus } from "../../lib/websocket";

type AmbientEnergyProps = {
  connection: AgentSocketStatus;
  agentState: AgentState | null;
};

export function AmbientEnergy({ connection, agentState }: AmbientEnergyProps) {
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    const updateVisibility = () => setPaused(document.visibilityState === "hidden");
    updateVisibility();
    document.addEventListener("visibilitychange", updateVisibility);
    return () => document.removeEventListener("visibilitychange", updateVisibility);
  }, []);

  const mode = connection === "open" ? agentState ?? "online" : connection;

  return (
    <div className={`kyra-ambient-energy kyra-ambient-energy--${mode}${paused ? " kyra-ambient-energy--paused" : ""}`} aria-hidden="true">
      <div className="kyra-ambient-energy__wash" />
      <svg className="kyra-ambient-energy__paths" viewBox="0 0 1440 900" preserveAspectRatio="none" focusable="false">
        <path className="kyra-ambient-energy__trace" d="M-40 218H146l27-25 34 52 34-27h204" />
        <path className="kyra-ambient-energy__spark" d="M-40 218H146l27-25 34 52 34-27h204" />
        <path className="kyra-ambient-energy__trace" d="M1480 598h-204l-30-29-35 54-35-25h-180" />
        <path className="kyra-ambient-energy__spark" d="M1480 598h-204l-30-29-35 54-35-25h-180" />
        <path className="kyra-ambient-energy__trace" d="M1170-40v142l26 28-42 48v154" />
        <path className="kyra-ambient-energy__spark" d="M1170-40v142l26 28-42 48v154" />
      </svg>
    </div>
  );
}
