import * as RadixPopover from "@radix-ui/react-popover";
import type { ReactNode } from "react";

type PopoverProps = {
  trigger: ReactNode;
  children: ReactNode;
  align?: RadixPopover.PopoverContentProps["align"];
  side?: RadixPopover.PopoverContentProps["side"];
  className?: string;
};

export function Popover({ trigger, children, align = "start", side = "bottom", className = "" }: PopoverProps) {
  return (
    <RadixPopover.Root>
      <RadixPopover.Trigger asChild>{trigger}</RadixPopover.Trigger>
      <RadixPopover.Portal>
        <RadixPopover.Content
          align={align}
          side={side}
          sideOffset={8}
          className={[
            "z-50 min-w-56 origin-[var(--radix-popover-content-transform-origin)] rounded-card border border-ink-300/15 bg-card p-3 shadow-cardH outline-none",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out data-[state=closed]:zoom-out-95",
            "data-[state=open]:animate-in data-[state=open]:fade-in data-[state=open]:zoom-in-95",
            "duration-fast ease-out",
            className
          ].filter(Boolean).join(" ")}
        >
          {children}
          <RadixPopover.Arrow className="fill-card" />
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  );
}

export const PopoverClose = RadixPopover.Close;
