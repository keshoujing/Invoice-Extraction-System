import { Suspense, lazy, useMemo } from "react";
import type { ComponentType } from "react";
import type { Tab } from "./lib/constants";
import { TabProvider, useTab } from "./shell/useTab";
import { ToastHost, ToastProvider } from "./shell/ToastHost";
import { TopNav } from "./shell/TopNav";
import { SpinnerPanel } from "./ui/Spinner";

const PendingTab = lazy(() => import("./pending/PendingTab"));
const ReviewTab = lazy(() => import("./review/ReviewTab"));
const ConfirmedTab = lazy(() => import("./confirmed/ConfirmedTab"));
const RulesTab = lazy(() => import("./rules/RulesTab"));

const tabComponents: Record<Tab, ComponentType> = {
  pending: PendingTab,
  review: ReviewTab,
  confirmed: ConfirmedTab,
  rules: RulesTab
};

function ActiveTab() {
  const [tab] = useTab();

  const TabComponent = useMemo(() => tabComponents[tab], [tab]);

  return (
    <main className="mx-auto w-full max-w-7xl flex-1 px-5 py-6">
      <Suspense fallback={<SpinnerPanel label="Loading tab" />}>
        <TabComponent />
      </Suspense>
    </main>
  );
}

function AppShell() {
  return (
    <div className="flex min-h-screen flex-col bg-gradient-to-b from-paper to-paper-deep text-ink-900">
      <TopNav />
      <ActiveTab />
      <ToastHost />
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <TabProvider>
        <AppShell />
      </TabProvider>
    </ToastProvider>
  );
}
