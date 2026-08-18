import { describe, expect, it } from "vitest";
import { buildPullRequestGraph, rankBottlenecks, type PullRequestInput } from "./graphModel";

const NOW = new Date("2026-08-18T02:00:00Z");
function pr(number: number, head: string, base = "main", overrides: Partial<PullRequestInput> = {}): PullRequestInput {
  return {
    number, title: `PR ${number}`, url: `https://github.com/example/pull/${number}`, author: "dev", base, head,
    headSha: `${number}`.repeat(40).slice(0, 40), draft: false, mergeable: true, createdAt: "2026-08-17T00:00:00Z", updatedAt: "2026-08-18T01:00:00Z",
    reviews: [{ user: "human", state: "APPROVED" }], checks: [{ name: "CI", status: "completed", conclusion: "success" }], ...overrides,
  };
}

describe("development PR graph model", () => {
  it("calculates stacked dependencies and transitive downstream", () => {
    const model = buildPullRequestGraph([pr(21,"a"),pr(22,"b","a"),pr(23,"c","b"),pr(24,"d","c")], { now: NOW });
    expect(model.find((item) => item.number === 22)?.dependencies).toEqual([21]);
    expect(model.find((item) => item.number === 21)?.downstream).toEqual([22,23,24]);
    expect(model.find((item) => item.number === 21)?.downstreamCount).toBe(3);
  });
  it("calculates an independent #40 → #41 stack", () => {
    const model = buildPullRequestGraph([pr(40,"producer"),pr(41,"projection","producer")], { now: NOW });
    expect(model.find((item) => item.number === 41)?.dependencies).toEqual([40]);
  });
  it("classifies failed CI and changes requested as blocked", () => {
    expect(buildPullRequestGraph([pr(1,"a","main",{checks:[{name:"CI",status:"completed",conclusion:"failure"}]})],{now:NOW})[0].status).toBe("BLOCKED");
    expect(buildPullRequestGraph([pr(1,"a","main",{reviews:[{user:"human",state:"CHANGES_REQUESTED"}]})],{now:NOW})[0].status).toBe("BLOCKED");
  });
  it("classifies stacked PRs as waiting", () => expect(buildPullRequestGraph([pr(1,"a"),pr(2,"b","a")],{now:NOW})[1].status).toBe("WAITING"));
  it("classifies approved green main PR as ready", () => expect(buildPullRequestGraph([pr(1,"a")],{now:NOW})[0].status).toBe("READY"));
  it("classifies missing human approval as needs review", () => expect(buildPullRequestGraph([pr(1,"a","main",{reviews:[]})],{now:NOW})[0].status).toBe("NEEDS_REVIEW"));
  it("marks stale PRs using the configured threshold", () => expect(buildPullRequestGraph([pr(1,"a","main",{updatedAt:"2026-08-14T00:00:00Z"})],{now:NOW,staleThresholdHours:72})[0].stale).toBe(true));
  it("orders the highest downstream bottleneck first", () => {
    const ranked = rankBottlenecks(buildPullRequestGraph([pr(21,"a"),pr(22,"b","a"),pr(23,"c","b"),pr(40,"x")],{now:NOW}));
    expect(ranked[0].number).toBe(21);
  });
});
