import type { ButtonHTMLAttributes } from "react";

import { cx } from "./surface-utils";

export type GestureControlProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children" | "onChange" | "onClick"> & {
  gesture: string;
  description: string;
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
};

/**
 * A configuration control, not a gesture detector. It deliberately manages no
 * persistence or hardware state; callers supply the controlled value.
 */
export function GestureControl({
  className,
  description,
  disabled,
  enabled,
  gesture,
  onEnabledChange,
  type = "button",
  ...props
}: GestureControlProps) {
  return (
    <button
      {...props}
      aria-label={`${gesture}: ${enabled ? "enabled" : "disabled"}. ${description}`}
      aria-pressed={enabled}
      className={cx("kyra-gesture-control", enabled && "kyra-gesture-control--enabled", className)}
      disabled={disabled}
      onClick={() => onEnabledChange(!enabled)}
      type={type}
    >
      <span className="kyra-gesture-control__copy">
        <span className="kyra-gesture-control__name">{gesture}</span>
        <span className="kyra-gesture-control__description">{description}</span>
      </span>
      <span aria-hidden="true" className="kyra-gesture-control__state">
        {enabled ? "On" : "Off"}
      </span>
    </button>
  );
}
