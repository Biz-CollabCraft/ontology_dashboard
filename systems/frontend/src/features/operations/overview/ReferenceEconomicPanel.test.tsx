import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { ReferenceEconomicPanel } from "./ReferenceEconomicPanel";
it("renders the 10-minute CNC result with explicit assumption labels and sources", () => {
 const html=renderToStaticMarkup(<ReferenceEconomicPanel assetId="CNC-S01-L03-03" minutes={10}/>);
 for(const text of ["10,575원","2,920원","12,453원","126,900원","가정 기반","실제 견적·확정 손실이 아닙니다","단가·가정·근거 보기"]) expect(html).toContain(text);
 expect(html).toContain("https://tsapps.nist.gov/");
});
it("does not convert missing stop time to zero loss", () => {
 const html=renderToStaticMarkup(<ReferenceEconomicPanel assetId="CMP-S01-L01-01"/>);
 expect(html).toContain("기본값 적용");expect(html).toContain("253,800원");expect(html).toContain("60");
});
