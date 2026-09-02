import { navigate } from "../../routing";
import { useEffect, useState } from "react";
import { Activity, ArrowLeft, ArrowRight, BarChart3, ClipboardCheck, FileText, Gauge, LockKeyhole, MapPinned, ShieldCheck, Wrench } from "lucide-react";
import { DisplayMenu } from "../../ui/foundry/DisplayMenu";

const PRODUCT_STORIES = [
  {
    eyebrow: "LIVE FACTORY STATUS",
    title: "이상 설비를 위치와 알림으로 먼저 찾습니다.",
    detail: "구역·셀 단위 설비 상태와 새 알림 수를 한 화면에서 보고, 클릭 한 번으로 해당 Event와 센서 근거까지 내려갑니다.",
    visual: "factory" as const,
  },
  {
    eyebrow: "ONE CASE · ROLE COMPOSED",
    title: "같은 사건을 역할마다 필요한 깊이로 봅니다.",
    detail: "엔지니어는 센서와 점검 근거, 운영 관리자는 생산 영향과 승인, 경영진은 KPI와 의사결정 병목을 같은 Case에서 확인합니다.",
    visual: "roles" as const,
  },
  {
    eyebrow: "TRACEABLE DECISION",
    title: "Event에서 Outcome까지 판단 근거가 끊기지 않습니다.",
    detail: "Evidence → Decision → Action → Maintenance → Outcome을 하나의 lineage로 연결해 누가 왜 무엇을 판단했는지 추적할 수 있습니다.",
    visual: "lineage" as const,
  },
  {
    eyebrow: "GROUNDED REPORTING",
    title: "보고서는 별도 문서가 아니라 업무 흐름의 산출물입니다.",
    detail: "현재 Case의 검증된 근거와 조치 결과를 바탕으로 역할별 보고 언어를 만들고, snapshot 기준을 유지한 채 경영 보고로 전환합니다.",
    visual: "report" as const,
  },
] as const;

function ProductStoryVisual({ kind }: { kind: (typeof PRODUCT_STORIES)[number]["visual"] }) {
  if (kind === "factory") return <div className="auth-story-factory" aria-hidden="true">
    {[0, 1, 2, 3].map((zone) => <section key={zone}><header><strong>{zone + 1}구역</strong><b>{zone === 1 ? "3" : zone === 3 ? "1" : ""}</b></header><div>{[0, 1, 2, 3, 4].map((cell) => <span key={cell} className={zone === 1 && cell === 2 ? "critical" : zone === 3 && cell === 1 ? "warning" : "normal"}>{cell === 2 && zone === 1 ? "!" : ""}</span>)}</div></section>)}
  </div>;
  if (kind === "roles") return <div className="auth-story-roles" aria-hidden="true">
    <article><MapPinned size={17} /><strong>Engineer</strong><span>Sensor · Evidence</span></article>
    <article><ClipboardCheck size={17} /><strong>Operations</strong><span>Impact · Decision</span></article>
    <article><BarChart3 size={17} /><strong>Executive</strong><span>KPI · Bottleneck</span></article>
  </div>;
  if (kind === "lineage") return <div className="auth-story-lineage" aria-hidden="true">
    {["Event", "Evidence", "Decision", "Action", "Outcome"].map((item, index) => <span key={item}><i>{index + 1}</i><strong>{item}</strong></span>)}
  </div>;
  return <div className="auth-story-report" aria-hidden="true"><FileText size={30} /><div><strong>Executive Brief</strong><span>Risk 72% · 4 Decision Cases</span><span>Production exposure · Maintenance outcome</span></div><em>AS-OF</em></div>;
}

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
  const [storyIndex, setStoryIndex] = useState(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => setStoryIndex((current) => (current + 1) % PRODUCT_STORIES.length), 6500);
    return () => window.clearInterval(timer);
  }, []);

  const story = PRODUCT_STORIES[storyIndex];
  const moveStory = (direction: -1 | 1) => setStoryIndex((current) => (current + direction + PRODUCT_STORIES.length) % PRODUCT_STORIES.length);

  return (
    <main className="auth-page">
      <header className="auth-platform-bar">
        <button className="auth-brand" onClick={() => navigate("/login")}><span className="brand-mark">RO</span><span><strong>Reliability Operations</strong><small>Predictive Maintenance Decision Workspace</small></span></button>
        <div><DisplayMenu className="auth-display-menu" /><span><Activity size={13} /> Monitoring live</span><span><ShieldCheck size={13} /> Decision traceable</span><span>Asia/Seoul</span></div>
      </header>
      <div className="auth-control-plane">
        <aside className="auth-resource-context">
          <header><span><Activity size={20} /></span><div><small>HANBIT TECH · RELIABILITY OPERATIONS</small><strong>설비 리스크를 운영 의사결정으로 연결</strong><small>Live status → Decision Case → Outcome</small></div></header>
          <section className="auth-product-story" aria-roledescription="carousel" aria-label="제품 주요 기능">
            <div className="auth-story-copy" key={story.eyebrow}>
              <span className="section-label">{story.eyebrow}</span>
              <h1>{story.title}</h1>
              <p>{story.detail}</p>
            </div>
            <ProductStoryVisual kind={story.visual} />
            <footer className="auth-story-controls">
              <div>{PRODUCT_STORIES.map((item, index) => <button type="button" key={item.eyebrow} className={index === storyIndex ? "is-active" : ""} onClick={() => setStoryIndex(index)} aria-label={`${index + 1}번째 제품 소개`} aria-current={index === storyIndex ? "true" : undefined} />)}</div>
              <span><button type="button" onClick={() => moveStory(-1)} aria-label="이전"><ArrowLeft size={14} /></button><button type="button" onClick={() => moveStory(1)} aria-label="다음"><ArrowRight size={14} /></button></span>
            </footer>
          </section>
          <section className="auth-value-strip">
            <span><Gauge size={15} /><strong>Live</strong><small>실시간 설비 상태</small></span>
            <span><ShieldCheck size={15} /><strong>Traceable</strong><small>근거 기반 판단</small></span>
            <span><Wrench size={15} /><strong>Closed loop</strong><small>정비 결과 확인</small></span>
          </section>
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
