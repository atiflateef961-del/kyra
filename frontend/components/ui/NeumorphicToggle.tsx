import type { ButtonHTMLAttributes } from "react";

import { cx } from "./surface-utils";

export type NeumorphicToggleProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children" | "onChange" | "onClick"> & {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
};

/** A controlled, keyboard-accessible switch. */
export function NeumorphicToggle({
  checked,
  className,
  disabled,
  label,
  onCheckedChange,
  type = "button",
  ...props
}: NeumorphicToggleProps) {
  return (
    <button
      {...props}
      aria-checked={checked}
      aria-label={label}
      className={cx("kyra-neumorphic-toggle", checked && "kyra-neumorphic-toggle--checked", className)}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      role="switch"
      type={type}
    >
      <span aria-hidden="true" className="kyra-neumorphic-toggle__thumb" />
    </button>
  );
}
