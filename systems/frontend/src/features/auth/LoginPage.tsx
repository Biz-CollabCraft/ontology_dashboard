import { FormEvent, useState } from "react";
import { ApiError } from "../../api";
import { navigate, operationsProjectPath, safeApplicationReturnPath } from "../../routing";
import type { AuthUser } from "../../types";
import { useAuth } from "./AuthContext";
import { AuthShell } from "./AuthShell";

const DEMO_ACCOUNTS = [
  {
    label: "운영 관리자",
    description: "판단 대기 · 생산 영향 · 정비 승인 · 보고 초안",
    email: "manager@ontology.local",
    password: "Manager!2026",
  },
  {
    label: "설비/공정 엔지니어",
    description: "설비 상태 · 센서 피쳐 · 점검 · 정비 이력 · 현장 메모",
    email: "engineer@ontology.local",
    password: "Engineer!2026",
  },
  {
    label: "경영진",
    description: "Executive Brief · 운영 리스크 · KPI · 의사결정 병목",
    email: "executive@ontology.local",
    password: "Executive!2026",
  },
] as const;

const PUBLIC_DEMO_HOSTS = new Set([
  "dashboard.oosu.dev",
  "127.0.0.1",
  "localhost",
]);

function shouldShowDemoAccounts() {
  const explicitFlag = import.meta.env.VITE_ENABLE_DEMO_ACCOUNTS;
  if (explicitFlag === "1" || explicitFlag === "true") return true;
  if (import.meta.env.DEV) return true;
  return typeof window !== "undefined" && PUBLIC_DEMO_HOSTS.has(window.location.hostname);
}

function roleAwareLandingPath(user: AuthUser): string {
  if (user.is_admin) return user.default_path;
  const projectId = user.active_project_id ?? user.project_scopes[0] ?? null;
  if (!projectId) return user.default_path;
  const roles = user.active_project_roles.length ? user.active_project_roles : user.roles;
  const params = new URLSearchParams({ dashboard: "workflow" });
  if (roles.includes("executive_viewer")) {
    params.set("view", "reports");
    params.set("report", "executive-brief");
    params.set("role", "process_manager");
  } else if (roles.includes("process_manager")) {
    params.set("view", "operations");
    params.set("role", "process_manager");
  } else if (roles.includes("maintenance_technician")) {
    params.set("view", "operations");
    params.set("role", "field_operator");
  } else {
    params.set("view", "overview");
    params.set("role", "field_operator");
  }
  return `${operationsProjectPath(projectId)}?${params.toString()}`;
}

export function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const user = await login(email, password);
      const returnTo = safeApplicationReturnPath(new URLSearchParams(window.location.search).get("returnTo"));
      navigate(returnTo ?? roleAwareLandingPath(user), { replace: true });
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === "pending_approval") {
        navigate(`/pending?email=${encodeURIComponent(email)}`);
        return;
      }
      setError(reason instanceof Error ? reason.message : "로그인하지 못했습니다.");
    } finally {
      setSubmitting(false);
    }
  }

  function selectDemo(value: string) {
    const account = DEMO_ACCOUNTS.find((item) => item.email === value);
    if (!account) return;
    setEmail(account.email);
    setPassword(account.password);
  }

  return (
    <AuthShell
      eyebrow="PREDICTIVE MAINTENANCE DECISION WORKSPACE"
      title="실시간 설비 현황에서 운영 판단과 경영 보고까지"
      description="같은 설비 이상 사건과 근거를 엔지니어의 조사, 운영 관리자의 판단, 경영진의 보고 언어로 연결합니다."
    >
      <form className="auth-form" onSubmit={submit}>
        <label>
          이메일
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="name@organization.com"
            required
          />
        </label>
        <label>
          비밀번호
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="비밀번호"
            required
          />
        </label>
        {error ? <div className="auth-error" role="alert">{error}</div> : null}
        <button className="primary auth-submit" type="submit" disabled={submitting}>
          {submitting ? "로그인 중…" : "로그인"}
        </button>
      </form>

      {shouldShowDemoAccounts() ? (
        <details className="demo-account-picker" open>
          <summary>역할별 Decision Workspace 체험</summary>
          <div className="demo-account-grid" role="group" aria-label="역할별 데모 계정">
            {DEMO_ACCOUNTS.map((account) => (
              <button
                key={account.email}
                className={`demo-account-card ${email === account.email ? "is-selected" : ""}`}
                type="button"
                onClick={() => selectDemo(account.email)}
              >
                <strong>{account.label}</strong>
                <span>{account.description}</span>
                <small>{account.email}</small>
              </button>
            ))}
          </div>
          <small>데이터는 하나지만 메뉴, KPI, 액션, Assistant 질문과 보고 흐름은 역할에 따라 달라집니다.</small>
        </details>
      ) : null}

      <p className="auth-footer-copy">
        계정이 없나요? <button className="link-button" type="button" onClick={() => navigate("/register")}>회원가입</button>
      </p>
    </AuthShell>
  );
}
