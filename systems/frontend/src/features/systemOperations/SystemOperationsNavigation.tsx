import { createContext, useContext, type ReactNode } from "react";
import { navigate as browserNavigate } from "../../routing";

type SystemOperationsNavigate = (path: string) => void;

const NavigationContext = createContext<SystemOperationsNavigate>(browserNavigate);
const PathnameContext = createContext("/system/operations/assets");

export function SystemOperationsNavigationProvider({
  navigate,
  pathname,
  children,
}: {
  navigate: SystemOperationsNavigate;
  pathname: string;
  children: ReactNode;
}) {
  return <NavigationContext.Provider value={navigate}><PathnameContext.Provider value={pathname}>{children}</PathnameContext.Provider></NavigationContext.Provider>;
}

export function useSystemOperationsNavigate() {
  return useContext(NavigationContext);
}

export function useSystemOperationsPathname() {
  return useContext(PathnameContext);
}
