"use client"

import * as React from "react"
import { DropdownMenu as Primitive } from "radix-ui"
import { cn } from "@/lib/utils"

const DropdownMenu = Primitive.Root
const DropdownMenuTrigger = Primitive.Trigger

function DropdownMenuContent({ className, sideOffset = 6, align = "end", ...props }: React.ComponentProps<typeof Primitive.Content>) {
  return (
    <Primitive.Portal>
      <Primitive.Content
        data-slot="dropdown-menu-content"
        sideOffset={sideOffset}
        align={align}
        className={cn(
          "z-50 min-w-56 overflow-hidden rounded-xl border bg-popover p-1.5 text-popover-foreground shadow-lg data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95",
          className
        )}
        {...props}
      />
    </Primitive.Portal>
  )
}

function DropdownMenuItem({ className, ...props }: React.ComponentProps<typeof Primitive.Item>) {
  return (
    <Primitive.Item
      data-slot="dropdown-menu-item"
      className={cn(
        "relative flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm outline-none select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground",
        className
      )}
      {...props}
    />
  )
}

export { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem }
