import { expect, it } from "vitest";
import { referenceEconomics } from "./referenceEconomics";
it("computes the 10-minute CNC example without adding production cost twice", () => {
 const e=referenceEconomics("CNC-S01-L03-03",10)!;
 expect(e).toMatchObject({hourlyProductionCost:126900,hourlyOpportunity:63450,stopExposure:10575,labor:2920,parts:12453,lostUnits:3,dailyCapacity:203});
});
it("separates compressor-dependent production and direct maintenance labor", () => {
 expect(referenceEconomics("CMP-S01-L01-01",10)).toMatchObject({hourlyOpportunity:253800,stopExposure:42300,labor:8760,parts:100000,lostUnits:9});
});
it("preserves unknown duration and zero and excludes unsupported machines", () => {
 expect(referenceEconomics("CNC-1",null)?.stopExposure).toBeNull();
 expect(referenceEconomics("CNC-1",NaN)?.lostUnits).toBeNull();
 expect(referenceEconomics("CNC-1",-1)?.stopExposure).toBeNull();
 expect(referenceEconomics("CNC-1",0)?.stopExposure).toBe(0);
 expect(referenceEconomics("UNKNOWN",10)).toBeNull();
});
