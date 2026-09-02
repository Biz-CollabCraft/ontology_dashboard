import { navigate } from "../../routing";
import { Activity, ArrowRight, ClipboardCheck, FileText, LockKeyhole, MapPinned, ShieldCheck } from "lucide-react";
import { DisplayMenu } from "../../ui/foundry/DisplayMenu";

export function AuthShell({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <main className="auth-page">
      <header className="auth-platform-bar">
        <button className="auth-brand" onClick={() => navigate("/login")}><span className="brand-mark">RO</span><span><strong>Reliability Operations</strong><small>Predictive Maintenance Decision Workspace</small></span></button>
        <div><DisplayMenu className="auth-display-menu" /><span><Activity size={13} /> Monitoring live</span><span><ShieldCheck size={13} /> Decision traceable</span><span>Asia/Seoul</span></div>
      </header>
      <div className="auth-control-plane">
        <aside className="auth-resource-context">
          <header><span><Activity size={20} /></span><div><small>RELIABILITY OPERATIONS</small><strong>기술 근거를 운영 판단으로</strong><small>설비 이상 발견 → 판단 → 보고</small></div></header>
          <section className="auth-problem-statement">
            <span className="section-label">BUSINESS PROBLEM</span>
            <h1>설비 이상 발견 뒤<br />판단과 보고까지의 시간차를 줄입니다.</h1>
            <p>현장의 기술 근거가 운영 판단과 경영 보고로 넘어가는 과정에서 생기는 맥락 손실을 하나의 Event · Evidence · Decision lineage로 연결합니다.</p>
          </section>
          <section className="auth-decision-flow">
            <span className="section-label">ONE EVENT, THREE OPERATING LEVELS</span>
            <div><b>01</b><MapPinned size={17} /><span><strong>Monitoring</strong><small>실시간 상태맵 · 센서 근거</small></span><em>LIVE</em></div>
            <ArrowRight className="auth-flow-arrow" size={15} />
            <div><b>02</b><ClipboardCheck size={17} /><span><strong>Decision Case</strong><small>생산 영향 · 승인 · 다음 행동</small></span><em>SNAPSHOT</em></div>
            <ArrowRight className="auth-flow-arrow" size={15} />
            <div><b>03</b><FileText size={17} /><span><strong>Executive Brief</strong><small>KPI · 병목 · 경영 보고</small></span><em>AS-OF</em></div>
          </section>
          <section className="auth-role-story">
            <span className="section-label">ROLE-AWARE EXPERIENCE</span>
            <div><span><strong>엔지니어</strong><small>왜 이상한가?</small></span><span><strong>운영 관리자</strong><small>무엇을 판단할까?</small></span><span><strong>경영진</strong><small>무엇을 보고받을까?</small></span></div>
          </section>
          <footer><span>DEMO PRINCIPLE</span><strong>Monitoring은 live · 보고서는 as-of</strong><small>새 관측이 와도 기존 Executive Brief는 자동으로 덮어쓰지 않습니다.</small></footer>
        </aside>
        <section className="auth-panel">
          <div className="auth-card">
            <div className="auth-card-heading"><span><LockKeyhole size={18} /></span><div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2></div></div>
            <p className="auth-description">{description}</p>
            {children}
            <footer><ShieldCheck size={12} /><span>Monitoring은 최신 관측을 따르고, Decision Case와 Executive Brief는 선택한 근거 snapshot을 기준으로 추적합니다.</span></footer>
          </div>
        </section>
      </div>
    </main>
  );
}
