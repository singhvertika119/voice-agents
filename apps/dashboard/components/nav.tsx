"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AudioLines, ChartColumn, House, Phone, PhoneCall, Settings, BookOpen, User, Ellipsis, Wrench } from "lucide-react";

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

export function MobileTabBar() {
  const path = usePathname();
  // DESIGN.md 6: Home, Calls, Agents, More
  const tabs = [items[0], items[4], items[1], { href: "/settings", label: "More", icon: Ellipsis }];
  return (
    <nav aria-label="Main" className="md:hidden fixed bottom-0 inset-x-0 h-16 bg-card border-t border-line grid grid-cols-4">
      {tabs.map(({ href, label, icon: Icon }, i) => (
        <Link
          key={label + i}
          href={href}
          className={`flex flex-col items-center justify-center gap-[3px] ${isCurrent(path, href) && label !== "More" ? "text-ink" : "text-ink-muted"}`}
        >
          <Icon size={20} strokeWidth={1.75} />
          <span className="text-[11px] font-medium">{label}</span>
        </Link>
      ))}
    </nav>
  );
}
