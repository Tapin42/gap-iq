import type { ReactNode } from "react";
import { useEffect } from "react";

import { ReplayBanner } from "./ReplayBanner";
import { useMeta } from "../lib/hooks";

export function AppShell({ children }: { children: ReactNode }) {
  const meta = useMeta();

  useEffect(() => {
    const base = "Gap IQ";
    document.title = meta?.mode === "replay" ? `REPLAY · ${base}` : base;
  }, [meta?.mode]);

  return (
    <div className="flex min-h-full flex-col">
      {meta && <ReplayBanner meta={meta} />}
      {children}
    </div>
  );
}
