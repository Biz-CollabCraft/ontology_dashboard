export function printProductionReport(dialog: HTMLElement) {
  const report = document.createElement("section");
  report.className = "production-impact-print-root";
  const content = dialog.cloneNode(true) as HTMLElement;
  content.removeAttribute("role");content.removeAttribute("aria-modal");content.removeAttribute("tabindex");
  content.querySelectorAll("button").forEach(button => button.remove());
  content.querySelectorAll("details").forEach(details => { details.open = true; });
  const stamp = document.createElement("p");
  stamp.textContent = "생산 영향 검토 보고서 · 출력 시각 " + new Date().toLocaleString("ko-KR");
  content.prepend(stamp);
  report.append(content);document.body.append(report);
  document.body.classList.add("production-impact-print-mode");
  try { window.print(); }
  finally { document.body.classList.remove("production-impact-print-mode");report.remove(); }
}
