import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import type { ReactNode } from "react";

export type DropdownItem = {
  label: ReactNode;
  onSelect?: () => void;
  disabled?: boolean;
  danger?: boolean;
};

type DropdownProps = {
  trigger: ReactNode;
  items: DropdownItem[];
  align?: DropdownMenu.DropdownMenuContentProps["align"];
};

export function Dropdown({ trigger, items, align = "end" }: DropdownProps) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>{trigger}</DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align={align}
          sideOffset={8}
          className={[
            "z-50 min-w-44 rounded-card border border-ink-300/15 bg-card p-1.5 shadow-cardH outline-none",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out data-[state=closed]:zoom-out-95",
            "data-[state=open]:animate-in data-[state=open]:fade-in data-[state=open]:zoom-in-95",
            "duration-fast ease-out"
          ].join(" ")}
        >
          {items.map((item, index) => (
            <DropdownMenu.Item
              key={index}
              disabled={item.disabled}
              onSelect={item.onSelect}
              className={[
                "cursor-pointer rounded-soft px-3 py-2 text-sm font-medium outline-none transition-colors duration-micro",
                "data-[disabled]:pointer-events-none data-[disabled]:opacity-45",
                item.danger ? "text-danger-text focus:bg-danger-bg" : "text-ink-700 focus:bg-brand-50 focus:text-brand-700"
              ].join(" ")}
            >
              {item.label}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export const DropdownSeparator = DropdownMenu.Separator;
