export const STALE_THRESHOLD_HOURS = 72;

export type FlowStatus = "READY" | "BLOCKED" | "WAITING" | "NEEDS_REVIEW";

export type ReviewRecord = {
  user: string;
  state: string;
  body?: string;
  submittedAt?: string;
  isBot?: boolean;
};

export type CheckRecord = {
  name: string;
  status: string;
  conclusion?: string | null;
  url?: string;
};

export type PullRequestInput = {
  number: number;
  title: string;
  url: string;
  author: string;
  base: string;
  head: string;
  headSha: string;
  draft: boolean;
  mergeable: boolean | null;
  mergeableState?: string;
  createdAt: string;
  updatedAt: string;
  reviews: ReviewRecord[];
  checks: CheckRecord[];
};

export type PullRequestModel = PullRequestInput & {
  status: FlowStatus;
  stale: boolean;
  staleDays: number;
  approvalCount: number;
  changesRequested: ReviewRecord[];
  dependencies: number[];
  downstream: number[];
  downstreamCount: number;
  bottleneckScore: number;
  blockers: string[];
};

function latestHumanReviewByUser(reviews: ReviewRecord[]) {
  const latest = new Map<string, ReviewRecord>();
  for (const review of reviews) {
    if (review.isBot || review.user.endsWith("[bot]")) continue;
    latest.set(review.user, review);
  }
  return [...latest.values()];
}
function hasFailedCheck(checks: CheckRecord[]) {
  return checks.some((check) => {
    const conclusion = (check.conclusion ?? "").toLowerCase();
    return ["failure", "cancelled", "timed_out", "action_required", "startup_failure"].includes(conclusion);
  });
}

function hasPendingCheck(checks: CheckRecord[]) {
  return checks.some((check) => check.status.toLowerCase() !== "completed");
}

function collectDownstream(start: number, adjacency: Map<number, number[]>) {
  const visited = new Set<number>();
  const queue = [...(adjacency.get(start) ?? [])];
  while (queue.length) {
    const current = queue.shift()!;
    if (visited.has(current)) continue;
    visited.add(current);
    queue.push(...(adjacency.get(current) ?? []));
  }
  return [...visited];
}

export function buildPullRequestGraph(
  pulls: PullRequestInput[],
  options: { mainBranch?: string; now?: Date; staleThresholdHours?: number } = {},
): PullRequestModel[] {
  const mainBranch = options.mainBranch ?? "main";
  const now = options.now ?? new Date();
  const staleThresholdHours = options.staleThresholdHours ?? STALE_THRESHOLD_HOURS;
  const byHead = new Map(pulls.map((pull) => [pull.head, pull]));
  const adjacency = new Map<number, number[]>();
  const dependencyMap = new Map<number, number[]>();

  for (const pull of pulls) {
    const upstream = byHead.get(pull.base);
    const dependencies = upstream ? [upstream.number] : [];
    dependencyMap.set(pull.number, dependencies);
    if (upstream) {
      adjacency.set(upstream.number, [...(adjacency.get(upstream.number) ?? []), pull.number]);
    }
  }

  return pulls.map((pull) => {
    const humanReviews = latestHumanReviewByUser(pull.reviews);
    const changesRequested = humanReviews.filter((review) => review.state.toUpperCase() === "CHANGES_REQUESTED");
    const approvalCount = humanReviews.filter((review) => review.state.toUpperCase() === "APPROVED").length;
    const dependencies = dependencyMap.get(pull.number) ?? [];
    const downstream = collectDownstream(pull.number, adjacency);
    const staleHours = Math.max(0, now.getTime() - new Date(pull.updatedAt).getTime()) / 3_600_000;
    const stale = staleHours >= staleThresholdHours;
    const staleDays = Math.floor(staleHours / 24);
    const blockers: string[] = [];

    if (pull.mergeable === false || pull.mergeableState === "dirty") blockers.push("Merge conflict");
    if (hasFailedCheck(pull.checks)) blockers.push("Failed CI/check");
    if (changesRequested.length) blockers.push("Changes requested");
    if (hasPendingCheck(pull.checks)) blockers.push("CI/check pending");

    let status: FlowStatus;
    if (blockers.some((item) => item !== "CI/check pending")) status = "BLOCKED";
    else if (dependencies.length > 0) status = "WAITING";
    else if (pull.base === mainBranch && !pull.draft && approvalCount > 0 && !hasPendingCheck(pull.checks)) status = "READY";
    else status = "NEEDS_REVIEW";

    const downstreamCount = downstream.length;
    const bottleneckScore = downstreamCount * 5
      + (status === "BLOCKED" ? 5 : 0)
      + (status === "WAITING" ? 2 : 0)
      + (status === "NEEDS_REVIEW" ? 2 : 0)
      + Math.min(staleDays, 10);

    return {
      ...pull,
      status,
      stale,
      staleDays,
      approvalCount,
      changesRequested,
      dependencies,
      downstream,
      downstreamCount,
      bottleneckScore,
      blockers,
    };
  });
}

export function rankBottlenecks(pulls: PullRequestModel[]) {
  return [...pulls].sort((a, b) => b.downstreamCount - a.downstreamCount || b.bottleneckScore - a.bottleneckScore || a.number - b.number);
}
export const BOTTLENECK_PRIORITY = "downstream-first" as const;
