import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";

interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  label: string;
  icon: ReactNode;
  tone?: "default" | "danger" | "primary";
}

export function IconButton({
  label,
  icon,
  tone = "default",
  className,
  type = "button",
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      className={`icon-btn icon-btn-${tone} ${className ?? ""}`}
      aria-label={label}
      data-tooltip={label}
      {...rest}
    >
      {icon}
    </button>
  );
}

export function useOutsideClose(
  ref: React.RefObject<HTMLElement | null>,
  onClose: () => void,
  active = true,
) {
  const handler = useRef(onClose);
  handler.current = onClose;
  useEffect(() => {
    if (!active) return;
    const listener = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) handler.current();
    };
    document.addEventListener("mousedown", listener);
    return () => document.removeEventListener("mousedown", listener);
  }, [ref, active]);
}
