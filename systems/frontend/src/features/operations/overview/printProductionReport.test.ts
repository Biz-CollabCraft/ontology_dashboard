// @vitest-environment jsdom
import { expect, it, vi } from "vitest";
import { printProductionReport } from "./printProductionReport";
it("prints only a snapshot of the report with sources expanded and controls removed", () => {
 const dialog=document.createElement("section");dialog.className="prb-dialog";
 dialog.innerHTML='<button>닫기</button><details><summary>근거</summary><p>단가 가정</p></details>';
 const print=vi.spyOn(window,"print").mockImplementation(() => {
  expect(document.body.classList.contains("production-impact-print-mode")).toBe(true);
  const report=document.querySelector(".production-impact-print-root")!;
  expect(report.querySelector("button")).toBeNull();
  expect(report.querySelector("details")?.open).toBe(true);
  expect(report.textContent).toContain("단가 가정");
  expect(report.textContent).toContain("출력 시각");
 });
 printProductionReport(dialog);
 expect(print).toHaveBeenCalledOnce();
 expect(dialog.querySelector("details")?.open).toBe(false);
 expect(document.querySelector(".production-impact-print-root")).toBeNull();
 expect(document.body.classList.contains("production-impact-print-mode")).toBe(false);
 print.mockRestore();
});
it("cleans print state even when printing fails", () => {
 const print=vi.spyOn(window,"print").mockImplementation(() => {throw Error("printer unavailable");});
 expect(() => printProductionReport(document.createElement("section"))).toThrow();
 expect(document.querySelector(".production-impact-print-root")).toBeNull();
 expect(document.body.classList.contains("production-impact-print-mode")).toBe(false);
 print.mockRestore();
});
