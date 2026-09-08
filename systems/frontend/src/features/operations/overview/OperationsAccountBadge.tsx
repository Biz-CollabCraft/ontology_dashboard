import { Moon, Sun } from "lucide-react";
import { useDisplayPreferences } from "../../../ui/foundry/displayPreferences";
import "./operationsTheme.css";

export function OperationsAccountBadge({ displayName, title }: { displayName: string; title: string }) {
  const { preferences, setTheme } = useDisplayPreferences();
  const isDark = preferences.theme === "dark" || (preferences.theme === "system" && document.documentElement.dataset.theme === "dark");
  const label = isDark ? "라이트 모드로 전환" : "다크 모드로 전환";
  return <>
    <span className="engineer-current-user" role="group" aria-label="로그인 계정">
      <b>{displayName}</b><small>{title}</small>
    </span>
    <button className="operations-theme-toggle" type="button" aria-label={label} title={label}
      onClick={() => setTheme(isDark ? "light" : "dark")}>
      {isDark ? <Moon size={20} aria-hidden="true" /> : <Sun size={20} aria-hidden="true" />}
    </button>
  </>;
}
