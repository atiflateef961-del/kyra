import type { Action } from "../../types/contracts";
import { ModalTransition } from "../motion/ModalTransition";
import { GlassPanel } from "./GlassPanel";
import { NeumorphicButton } from "./NeumorphicButton";

export type ConfirmActionDialogProps = {
  action: Action | null;
  busy?: boolean;
  onApprove: () => void;
  onCancel: () => void;
};

export function ConfirmActionDialog({ action, busy = false, onApprove, onCancel }: ConfirmActionDialogProps) {
  const isOpen = action !== null;
  const titleId = "kyra-confirm-action-title";
  const descriptionId = "kyra-confirm-action-description";

  return (
    <ModalTransition isOpen={isOpen} onBackdropClick={onCancel}>
      <GlassPanel
        aria-describedby={descriptionId}
        aria-labelledby={titleId}
        aria-modal="true"
        as="div"
        role="dialog"
      >
        <h2 id={titleId}>Confirm action</h2>
        <p id={descriptionId}>
          Kyra wants to run {action?.identifier ?? "an action"}.
          {action?.risk_level === "high" ? " This is a high-risk action." : ""}
        </p>
        <div>
          <NeumorphicButton disabled={busy} onClick={onCancel} type="button">
            {busy ? "Working..." : "Cancel"}
          </NeumorphicButton>
          <NeumorphicButton disabled={busy} onClick={onApprove} tone="primary" type="button">
            Approve
          </NeumorphicButton>
        </div>
      </GlassPanel>
    </ModalTransition>
  );
}
