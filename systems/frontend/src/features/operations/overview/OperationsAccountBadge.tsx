import { useDisplayPreferences } from "../../../ui/foundry/displayPreferences";
import "./operationsTheme.css";

export function OperationsAccountBadge({ displayName, title }: { displayName: string; title: string }) {
  const { preferences, setTheme } = useDisplayPreferences();
  return <>
    <span className="engineer-current-user" role="group" aria-label="로그인 계정">
      <b>{displayName}</b><small>{title}</small>
    </span>
    <div className="operations-theme-switch" role="group" aria-label="화면 모드">
      <button type="button" aria-pressed={preferences.theme === "light"} onClick={() => setTheme("light")}>라이트 모드</button>
      <button type="button" aria-pressed={preferences.theme === "dark"} onClick={() => setTheme("dark")}>다크 모드</button>
    </div>
  </>;
}
