import { useEffect } from "react";

const THEME_KEY = "ontology-dashboard:reliability-theme";
const LOCALE_KEY = "ontology-dashboard:reliability-locale";

export function isReliabilityPreviewLocation(): boolean {
  const queryEnabled = new URLSearchParams(window.location.search).get("workspace_shell") === "reliability";
  if (queryEnabled) return true;
  const basePath = import.meta.env.BASE_URL.replace(/\/+$/, "");
  const pathname = window.location.pathname;
  if (basePath === "") {
    return pathname === "/" || pathname === "/app" || /^\/app\/projects\/[^/]+\/operations/.test(pathname);
  }
  if (basePath !== "/reliability-preview") return false;
  return pathname.startsWith(`${basePath}/app/projects/`)
    && (pathname.includes("/operations") || pathname.includes("/operations"));
}

export function ReliabilityRoutePlaceholder() {
  const theme = window.localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light";
  const locale = window.localStorage.getItem(LOCALE_KEY) === "en-US" ? "en-US" : "ko-KR";

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.lang = locale;
  }, [locale, theme]);

  const params = new URLSearchParams(window.location.search);
  const engineerFactory = /^\/app\/projects\/[^/]+\/operations/.test(window.location.pathname)
    && params.get("role") === "field_operator"
    && (params.get("view") === "overview" || params.get("view") === null);

  if (engineerFactory) {
    return (
      <main className={`engineer-route-loading is-${theme}`} aria-busy="true" aria-label="공장 현황 데이터 로딩 중">
        <header><div><strong>공장 현황</strong><span>설비 데이터를 연결하고 있습니다</span></div><b>연결 확인 중</b></header>
        <section className="engineer-route-loading__kpis">
          {["즉시 조치 필요 설비", "가동 중 설비", "예상 정지 영향"].map((label) => <article key={label}><span>{label}</span><strong>—</strong><small>데이터 로딩 중</small></article>)}
        </section>
        <section className="engineer-route-loading__main">
          <article><strong>라인 · 셀 · 설비 상태</strong><span>데이터 로딩 중</span></article>
          <article><strong>위험 점수 추세 · 최근 12시간</strong><span>데이터 로딩 중</span></article>
          <article><strong>최근 이벤트</strong><span>데이터 로딩 중</span></article>
        </section>
        <section className="engineer-route-loading__bottom"><article><strong>선택 설비 근거 요약</strong><span>데이터 로딩 중</span></article><article><strong>실시간 상태 신호</strong><span>데이터 로딩 중</span></article></section>
      </main>
    );
  }

  return (
    <main className={`reliability-route-placeholder is-${theme}`} aria-busy="true" aria-label="Reliability workspace 준비 중">
      <header className="reliability-route-placeholder__topbar">
        <strong>CollabCraft</strong>
        <span />
      </header>
      <div className="reliability-route-placeholder__body">
        <aside aria-hidden="true">
          <i className="wide" /><i /><i /><i /><b />
        </aside>
        <section aria-hidden="true">
          <i className="eyebrow" />
          <i className="title" />
          <i className="copy" />
          <article>
            <i className="kicker" /><i className="hero" /><i className="copy" />
            <div><b /><b /><b /><b /></div>
          </article>
          <div className="reliability-route-placeholder__cards"><article /><article /></div>
        </section>
      </div>
      <footer aria-hidden="true"><i /><i /><i /><i /></footer>
    </main>
  );
}
