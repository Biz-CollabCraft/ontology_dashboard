import type { CheckRecord, PullRequestInput, ReviewRecord } from "./graphModel";

const OWNER = "Biz-CollabCraft";
const REPO = "ontology_dashboard";
const API_ROOT = `https://api.github.com/repos/${OWNER}/${REPO}`;
const CACHE_KEY = "ontology-dashboard:dev-dashboard:v1";
const CACHE_MS = 60_000;

export type CommitRecord = {
  sha: string;
  message: string;
  author: string;
  timestamp: string;
  parents: string[];
  branch: string;
  prNumber?: number;
};

export type GitHubSnapshot = {
  pulls: PullRequestInput[];
  commits: CommitRecord[];
  fetchedAt: string;
  rateLimitRemaining?: number;
};

type CachedSnapshot = { expiresAt: number; snapshot: GitHubSnapshot };

function cacheRead(): GitHubSnapshot | null {
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const cached = JSON.parse(raw) as CachedSnapshot;
    if (cached.expiresAt < Date.now()) return null;
    return cached.snapshot;
  } catch {
    return null;
  }
}
function cacheWrite(snapshot: GitHubSnapshot) {
  try {
    window.localStorage.setItem(CACHE_KEY, JSON.stringify({ expiresAt: Date.now() + CACHE_MS, snapshot } satisfies CachedSnapshot));
  } catch {
    // Storage can be unavailable in hardened browser contexts; live fetch still works.
  }
}

async function fetchGitHub<T>(path: string): Promise<{ data: T; remaining?: number }> {
  const response = await fetch(`${API_ROOT}${path}`, {
    headers: { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" },
  });
  const remainingHeader = response.headers.get("x-ratelimit-remaining");
  const remaining = remainingHeader ? Number(remainingHeader) : undefined;
  if (!response.ok) {
    const detail = await response.text();
    if (response.status === 403 && remaining === 0) {
      throw new Error("GitHub public API rate limit reached. Wait for reset or use a server-side authenticated aggregator.");
    }
    throw new Error(`GitHub API ${response.status}: ${detail.slice(0, 180)}`);
  }
  return { data: await response.json() as T, remaining };
}

function normalizeReview(review: any): ReviewRecord {
  return {
    user: review.user?.login ?? "unknown",
    state: review.state ?? "COMMENTED",
    body: review.body ?? "",
    submittedAt: review.submitted_at ?? undefined,
    isBot: review.user?.type === "Bot" || String(review.user?.login ?? "").endsWith("[bot]"),
  };
}

function normalizeCheck(check: any): CheckRecord {
  return {
    name: check.name ?? "check",
    status: check.status ?? "queued",
    conclusion: check.conclusion ?? null,
    url: check.html_url ?? check.details_url ?? undefined,
  };
}

function normalizeCommit(commit: any, branch: string, prNumber?: number): CommitRecord {
  return {
    sha: commit.sha,
    message: String(commit.commit?.message ?? "Commit").split("\n")[0],
    author: commit.commit?.author?.name ?? commit.author?.login ?? "unknown",
    timestamp: commit.commit?.author?.date ?? new Date(0).toISOString(),
    parents: (commit.parents ?? []).map((parent: any) => parent.sha),
    branch,
    prNumber,
  };
}

export async function loadGitHubSnapshot(options: { force?: boolean } = {}): Promise<GitHubSnapshot> {
  if (!options.force) {
    const cached = cacheRead();
    if (cached) return cached;
  }

  const pullList = await fetchGitHub<any[]>("/pulls?state=open&per_page=100&sort=updated&direction=desc");
  let rateLimitRemaining = pullList.remaining;

  const pulls = await Promise.all(pullList.data.map(async (summary) => {
    const [detailResult, reviewsResult, checksResult] = await Promise.all([
      fetchGitHub<any>(`/pulls/${summary.number}`),
      fetchGitHub<any[]>(`/pulls/${summary.number}/reviews?per_page=100`),
      fetchGitHub<any>(`/commits/${summary.head.sha}/check-runs?per_page=100`),
    ]);
    rateLimitRemaining = Math.min(...[rateLimitRemaining, detailResult.remaining, reviewsResult.remaining, checksResult.remaining].filter((value): value is number => typeof value === "number"));
    const detail = detailResult.data;
    return {
      number: detail.number,
      title: detail.title,
      url: detail.html_url,
      author: detail.user?.login ?? "unknown",
      base: detail.base?.ref ?? "main",
      head: detail.head?.ref ?? "unknown",
      headSha: detail.head?.sha ?? summary.head.sha,
      draft: Boolean(detail.draft),
      mergeable: typeof detail.mergeable === "boolean" ? detail.mergeable : null,
      mergeableState: detail.mergeable_state,
      createdAt: detail.created_at,
      updatedAt: detail.updated_at,
      reviews: reviewsResult.data.map(normalizeReview),
      checks: (checksResult.data.check_runs ?? []).map(normalizeCheck),
    } satisfies PullRequestInput;
  }));

  const commitRequests = [
    fetchGitHub<any[]>("/commits?sha=main&per_page=30").then((result) => result.data.map((commit) => normalizeCommit(commit, "main"))),
    ...pulls.map((pull) => fetchGitHub<any[]>(`/pulls/${pull.number}/commits?per_page=30`).then((result) => result.data.map((commit) => normalizeCommit(commit, pull.head, pull.number)))),
  ];
  const commitGroups = await Promise.all(commitRequests);
  const uniqueCommits = new Map<string, CommitRecord>();
  for (const commit of commitGroups.flat()) {
    const existing = uniqueCommits.get(commit.sha);
    if (!existing || existing.branch === "main") uniqueCommits.set(commit.sha, commit);
  }

  const snapshot: GitHubSnapshot = {
    pulls,
    commits: [...uniqueCommits.values()].sort((a, b) => b.timestamp.localeCompare(a.timestamp)).slice(0, 100),
    fetchedAt: new Date().toISOString(),
    rateLimitRemaining,
  };
  cacheWrite(snapshot);
  return snapshot;
}
export const DEV_DASHBOARD_CACHE_TTL_MS = CACHE_MS;
