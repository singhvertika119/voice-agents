"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { AudioLines, ChartColumn, House, Phone, PhoneCall, Settings, BookOpen, User, Ellipsis, Wrench, LogOut, X } from "lucide-react";

const items = [
  { href: "/", label: "Home", icon: House },
  { href: "/agents", label: "Agents", icon: AudioLines },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/tools", label: "Tools", icon: Wrench },
  { href: "/calls", label: "Calls", icon: Phone },
  { href: "/callbacks", label: "Callbacks", icon: PhoneCall },
  { href: "/settings", label: "Settings", icon: Settings },
];
// TODO(design): Contacts and Analytics routes are built when the feature exists (DESIGN.md section 7).
const soon = [
  { label: "Contacts", icon: User },
  { label: "Analytics", icon: ChartColumn },
];

function isCurrent(path: string, href: string) {
  return href === "/" ? path === "/" : path.startsWith(href);
}

export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="size-7 rounded-md bg-ink text-on-ink inline-flex items-center justify-center" aria-hidden>
        <AudioLines size={16} strokeWidth={2} />
      </span>
      <span className="text-[15px] font-semibold">Voice Agents</span>
    </div>
  );
}

export function SideNav({ email }: { email: string }) {
  const path = usePathname();
  return (
    <aside className="hidden md:flex flex-[1_1_200px] max-w-[232px] bg-card border-r border-line px-4 py-6 flex-col gap-7">
      <Logo />
      <nav aria-label="Main" className="flex flex-col gap-1">
        {items.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            aria-current={isCurrent(path, href) ? "page" : undefined}
            className={`h-10 px-2.5 flex items-center gap-2.5 rounded-md text-sm hover:bg-muted ${
              isCurrent(path, href) ? "bg-muted text-ink font-medium" : "text-ink-secondary"
            }`}
          >
            <Icon size={18} strokeWidth={1.75} /> {label}
          </Link>
        ))}
        {soon.map(({ label, icon: Icon }) => (
          <span key={label} className="h-10 px-2.5 flex items-center gap-2.5 rounded-md text-sm text-ink-faint">
            <Icon size={18} strokeWidth={1.75} /> {label}
            <span className="ml-auto text-xs">Soon</span>
          </span>
        ))}
      </nav>
      <div className="mt-auto flex flex-col gap-2">
        <span className="text-[13px] text-ink-muted truncate">{email}</span>
        <form action="/auth/signout" method="post">
          <button className="text-sm text-ink-secondary hover:text-ink h-10">Sign out</button>
        </form>
      </div>
    </aside>
  );
}

export function MobileTabBar({ email }: { email: string }) {
  const path = usePathname();
  // Remembers the page the menu was opened on, so following a link (a new path) closes it without an effect.
  const [openOn, setOpenOn] = useState<string | null>(null);
  const open = openOn === path;
  const setOpen = (v: boolean) => setOpenOn(v ? path : null);
  // DESIGN.md 6: Home, Calls, Agents, More. "More" opens a sheet with the remaining pages and Sign out, which the side
  // navigation shows on larger screens.
  const tabs = [items[0], items[4], items[1]];
  const more = items.filter((x) => !tabs.includes(x));
  const moreCurrent = more.some((x) => isCurrent(path, x.href));

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpenOn(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      {open && (
        <div className="md:hidden fixed inset-0 z-40 bg-ink/30" onClick={() => setOpen(false)}>
          <div
            id="more-menu"
            role="dialog"
            aria-label="More"
            className="absolute bottom-16 inset-x-0 bg-card border-t border-line rounded-t-xl px-4 pt-3 pb-4 flex flex-col gap-1"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between h-10">
              <span className="text-[13px] text-ink-muted truncate">{email}</span>
              <button onClick={() => setOpen(false)} aria-label="Close" className="size-10 inline-flex items-center justify-center text-ink-muted">
                <X size={18} strokeWidth={1.75} />
              </button>
            </div>
            {more.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                aria-current={isCurrent(path, href) ? "page" : undefined}
                className={`h-12 px-2.5 flex items-center gap-3 rounded-md text-[15px] ${isCurrent(path, href) ? "bg-muted text-ink font-medium" : "text-ink-secondary"}`}
              >
                <Icon size={18} strokeWidth={1.75} /> {label}
              </Link>
            ))}
            <form action="/auth/signout" method="post" className="border-t border-line mt-1 pt-1">
              <button className="w-full h-12 px-2.5 flex items-center gap-3 rounded-md text-[15px] text-ink-secondary">
                <LogOut size={18} strokeWidth={1.75} /> Sign out
              </button>
            </form>
          </div>
        </div>
      )}
      <nav aria-label="Main" className="md:hidden fixed bottom-0 inset-x-0 z-50 h-16 bg-card border-t border-line grid grid-cols-4">
        {tabs.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={`flex flex-col items-center justify-center gap-[3px] ${isCurrent(path, href) && !open ? "text-ink" : "text-ink-muted"}`}
          >
            <Icon size={20} strokeWidth={1.75} />
            <span className="text-[11px] font-medium">{label}</span>
          </Link>
        ))}
        <button
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-controls="more-menu"
          className={`flex flex-col items-center justify-center gap-[3px] ${open || moreCurrent ? "text-ink" : "text-ink-muted"}`}
        >
          <Ellipsis size={20} strokeWidth={1.75} />
          <span className="text-[11px] font-medium">More</span>
        </button>
      </nav>
    </>
  );
}
