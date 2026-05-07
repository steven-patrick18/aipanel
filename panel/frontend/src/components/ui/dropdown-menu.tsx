import * as React from "react";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { cn } from "@/lib/utils";

export const DropdownMenu = Dropdown.Root;
export const DropdownMenuTrigger = Dropdown.Trigger;

export const DropdownMenuContent = React.forwardRef<
  React.ElementRef<typeof Dropdown.Content>,
  React.ComponentPropsWithoutRef<typeof Dropdown.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <Dropdown.Portal>
    <Dropdown.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        "z-50 min-w-[10rem] overflow-hidden rounded-md border border-slate-200 bg-white p-1 shadow-md",
        className
      )}
      {...props}
    />
  </Dropdown.Portal>
));
DropdownMenuContent.displayName = Dropdown.Content.displayName;

export const DropdownMenuItem = React.forwardRef<
  React.ElementRef<typeof Dropdown.Item>,
  React.ComponentPropsWithoutRef<typeof Dropdown.Item>
>(({ className, ...props }, ref) => (
  <Dropdown.Item
    ref={ref}
    className={cn(
      "relative flex cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-sm outline-none",
      "focus:bg-slate-100 focus:text-slate-900",
      "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
      className
    )}
    {...props}
  />
));
DropdownMenuItem.displayName = Dropdown.Item.displayName;

export const DropdownMenuSeparator = React.forwardRef<
  React.ElementRef<typeof Dropdown.Separator>,
  React.ComponentPropsWithoutRef<typeof Dropdown.Separator>
>(({ className, ...props }, ref) => (
  <Dropdown.Separator
    ref={ref}
    className={cn("-mx-1 my-1 h-px bg-slate-200", className)}
    {...props}
  />
));
DropdownMenuSeparator.displayName = Dropdown.Separator.displayName;

export const DropdownMenuLabel = React.forwardRef<
  React.ElementRef<typeof Dropdown.Label>,
  React.ComponentPropsWithoutRef<typeof Dropdown.Label>
>(({ className, ...props }, ref) => (
  <Dropdown.Label
    ref={ref}
    className={cn("px-2 py-1.5 text-xs font-semibold text-slate-500", className)}
    {...props}
  />
));
DropdownMenuLabel.displayName = Dropdown.Label.displayName;
