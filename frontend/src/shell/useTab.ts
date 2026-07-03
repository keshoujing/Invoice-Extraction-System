import { createContext, createElement, useContext, useEffect, useMemo, useState } from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import type { Tab } from "../lib/constants";
import { storedTab, storeTab } from "../lib/storage";

type TabContextValue = readonly [Tab, Dispatch<SetStateAction<Tab>>];

const TabContext = createContext<TabContextValue | null>(null);

type TabProviderProps = {
  children: ReactNode;
};

export function TabProvider({ children }: TabProviderProps) {
  const [tab, setTab] = useState<Tab>(storedTab);

  useEffect(() => {
    storeTab(tab);
  }, [tab]);

  const value = useMemo<TabContextValue>(() => [tab, setTab] as const, [tab]);

  return createElement(TabContext.Provider, { value }, children);
}

export function useTab(): TabContextValue {
  const context = useContext(TabContext);
  if (!context) {
    throw new Error("useTab must be used inside TabProvider");
  }
  return context;
}

export const tabOrder: Tab[] = ["pending", "review", "confirmed", "rules"];

export function tabLabel(tab: Tab): string {
  const labels: Record<Tab, string> = {
    pending: "Pending",
    review: "Review Review",
    confirmed: "Confirmed Confirmed",
    rules: "Rules Rules"
  };
  return labels[tab];
}
