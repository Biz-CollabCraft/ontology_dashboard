import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { OperationsAccountBadge } from "./OperationsAccountBadge";

describe("account identity across operations roles", () => {
  it.each(["설비 엔지니어", "보전팀", "생산관리자"])("shows the signed-in name and %s role", (title) => {
    const html = renderToStaticMarkup(<OperationsAccountBadge displayName="김담당" title={title} />);
    expect(html).toContain('aria-label="로그인 계정"');
    expect(html).toContain("<b>김담당</b>");
    expect(html).toContain("<small>" + title + "</small>");
    expect(html.indexOf("김담당")).toBeLessThan(html.indexOf(title));
  });
  it("escapes account-provided display names", () => {
    const html = renderToStaticMarkup(<OperationsAccountBadge displayName="<script>name</script>" title="보전팀" />);
    expect(html).not.toContain("<script>");
  });
});
