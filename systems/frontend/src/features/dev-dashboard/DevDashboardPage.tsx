import { useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import { AlertTriangle, GitBranch, RefreshCw, Search } from "lucide-react";
import "@xyflow/react/dist/style.css";
import "./dev-dashboard.css";
import { buildPullRequestGraph, rankBottlenecks, type PullRequestModel } from "./graphModel";
import { loadGitHubSnapshot, type CommitRecord, type GitHubSnapshot } from "./githubClient";

const STATUS_ORDER = ["READY", "BLOCKED", "WAITING", "NEEDS_REVIEW"] as const;

function statusLabel(status: PullRequestModel["status"]) {
  return status === "NEEDS_REVIEW" ? "NEEDS REVIEW" : status;
}
function prNodesAndEdges(pulls: PullRequestModel[], selected: number | null) {
  const levels = new Map<number, number>();
  const byNumber = new Map(pulls.map((pull) => [pull.number, pull]));
  const levelOf = (pull: PullRequestModel): number => {
    if (levels.has(pull.number)) return levels.get(pull.number)!;
    const upstream = pull.dependencies[0] ? byNumber.get(pull.dependencies[0]) : undefined;
    const level = upstream ? levelOf(upstream) + 1 : 0;
    levels.set(pull.number, level);
    return level;
  };
  const lanes = new Map<number, number>();
  const nodes: Node[] = pulls.map((pull) => {
    const level = levelOf(pull);
    const lane = lanes.get(level) ?? 0;
    lanes.set(level, lane + 1);
    const active = selected === pull.number;
    return {
      id: `pr-${pull.number}`,
      position: { x: level * 330, y: lane * 190 },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      data: { label: (
        <div className="dev-pr-node-content">
          <div className="dev-pr-node-top"><strong>#{pull.number}</strong><span className={`dev-status dev-status-${pull.status.toLowerCase().replace("_", "-")}`}>{statusLabel(pull.status)}</span></div>
          <div className="dev-pr-title">{pull.title}</div>
          <div className="dev-pr-meta">{pull.author} · {pull.head}</div>
          <div className="dev-pr-node-bottom"><span>CI {pull.checks.some((check) => check.status !== "completed") ? "…" : pull.checks.some((check) => check.conclusion === "failure") ? "✕" : "✓"}</span><span>Review {pull.approvalCount ? "✓" : "—"}</span><span>blocks {pull.downstreamCount}</span></div>
        </div>
      ) },
      className: `dev-pr-node dev-pr-node-${pull.status.toLowerCase().replace("_", "-")} ${active ? "is-selected" : ""}`,
      style: { width: 285 },
    };
  });
  const edges: Edge[] = pulls.flatMap((pull) => pull.dependencies.map((dependency) => ({
    id: `edge-${dependency}-${pull.number}`,
    source: `pr-${dependency}`,
    target: `pr-${pull.number}`,
    markerEnd: { type: MarkerType.ArrowClosed },
    animated: selected === pull.number || selected === dependency,
  })));
  return { nodes, edges };
}

function CommitGraph({ commits }: { commits: CommitRecord[] }) {
  const branchOrder = [...new Set(commits.map((commit) => commit.branch))];
  const nodes: Node[] = commits.slice(0, 80).map((commit, index) => ({
    id: commit.sha,
    position: { x: index * 155, y: Math.max(0, branchOrder.indexOf(commit.branch)) * 105 },
    data: { label: <div className="dev-commit-node"><strong>{commit.sha.slice(0, 7)}</strong><span>{commit.message}</span><small>{commit.prNumber ? `PR #${commit.prNumber}` : commit.branch}</small></div> },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    className: "dev-commit-flow-node",
    style: { width: 140 },
  }));
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges: Edge[] = commits.slice(0, 80).flatMap((commit) => commit.parents.filter((parent) => nodeIds.has(parent)).map((parent) => ({
    id: `${parent}-${commit.sha}`,
    source: parent,
    target: commit.sha,
  })));
  return <div className="dev-graph-canvas"><ReactFlow nodes={nodes} edges={edges} fitView minZoom={0.15}><Background /><Controls /></ReactFlow></div>;
}

function nextAction(pull: PullRequestModel) {
  if (pull.status === "READY") return "Merge decision needed";
  if (pull.status === "BLOCKED") return pull.blockers[0] ?? "Resolve blocker";
  if (pull.status === "WAITING") return `Waiting for #${pull.dependencies[0]}`;
  return "Human review needed";
}

export function DevDashboardPage() {
  const [snapshot, setSnapshot] = useState<GitHubSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<number | null>(null);
  const [tab, setTab] = useState<"flow" | "commits">("flow");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [authorFilter, setAuthorFilter] = useState("ALL");

  async function refresh(force = false) {
    setLoading(true); setError(null);
    try { setSnapshot(await loadGitHubSnapshot({ force })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Failed to load GitHub data"); }
    finally { setLoading(false); }
  }

  useEffect(() => { void refresh(false); }, []);

  const pulls = useMemo(() => snapshot ? buildPullRequestGraph(snapshot.pulls) : [], [snapshot]);
  const filtered = useMemo(() => pulls.filter((pull) => {
    const matchesQuery = !query || `${pull.number} ${pull.title} ${pull.author} ${pull.head}`.toLowerCase().includes(query.toLowerCase());
    return matchesQuery
      && (statusFilter === "ALL" || pull.status === statusFilter)
      && (authorFilter === "ALL" || pull.author === authorFilter);
  }), [pulls, query, statusFilter, authorFilter]);
  const ranked = useMemo(() => rankBottlenecks(pulls).slice(0, 5), [pulls]);
  const selectedPull = pulls.find((pull) => pull.number === selected) ?? null;
  const graph = useMemo(() => prNodesAndEdges(filtered, selected), [filtered, selected]);

  const counts = Object.fromEntries(STATUS_ORDER.map((status) => [status, pulls.filter((pull) => pull.status === status).length]));

  return (
    <main className="dev-dashboard-shell" data-testid="dev-dashboard">
      <header className="dev-dashboard-header">
        <div><div className="dev-eyebrow"><GitBranch size={15} /> DEVELOPMENT FLOW</div><h1>PR Flow Dashboard</h1><p>What should we resolve now to unblock the most work?</p></div>
        <div className="dev-refresh-group"><span>{snapshot ? `Updated ${new Date(snapshot.fetchedAt).toLocaleTimeString()} · rate ${snapshot.rateLimitRemaining ?? "?"}` : "Live GitHub read-only"}</span><button onClick={() => void refresh(true)} disabled={loading}><RefreshCw size={16} /> Refresh</button></div>
      </header>

      <section className="dev-summary-grid">
        <div><span>Open PRs</span><strong>{pulls.length}</strong></div>
        <div><span>Ready</span><strong>{counts.READY ?? 0}</strong></div>
        <div><span>Blocked</span><strong>{counts.BLOCKED ?? 0}</strong></div>
        <div><span>Waiting</span><strong>{counts.WAITING ?? 0}</strong></div>
        <div><span>Needs Review</span><strong>{counts.NEEDS_REVIEW ?? 0}</strong></div>
      </section>

      {error && <div className="dev-error" role="alert"><AlertTriangle size={18} /><div><strong>GitHub data unavailable</strong><p>{error}</p></div></div>}
      {loading && !snapshot && <div className="dev-loading">Reading current Pull Requests, reviews, checks and commits…</div>}

      <div className="dev-tab-row"><button className={tab === "flow" ? "active" : ""} onClick={() => setTab("flow")}>PR Flow</button><button className={tab === "commits" ? "active" : ""} onClick={() => setTab("commits")}>Commit Graph</button></div>

      {snapshot && tab === "flow" && <div className="dev-layout">
        <section className="dev-main-panel">
          <div className="dev-toolbar"><label><Search size={16} /><input aria-label="Search PRs" placeholder="Search PR, title, branch, author" value={query} onChange={(event) => setQuery(event.target.value)} /></label><select aria-label="Status filter" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="ALL">All status</option>{STATUS_ORDER.map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}</select><select aria-label="Author filter" value={authorFilter} onChange={(event) => setAuthorFilter(event.target.value)}><option value="ALL">All authors</option>{[...new Set(pulls.map((pull) => pull.author))].sort().map((author) => <option key={author} value={author}>{author}</option>)}</select></div>
          {filtered.length ? <div className="dev-graph-canvas" data-testid="pr-flow-graph" data-edge-count={graph.edges.length}><ReactFlow nodes={graph.nodes} edges={graph.edges} fitView minZoom={0.35} onNodeClick={(_, node) => setSelected(Number(node.id.replace("pr-", "")))}><Background /><MiniMap pannable zoomable /><Controls /></ReactFlow></div> : <div className="dev-empty">No Pull Requests match the current filter.</div>}
        </section>
        <aside className="dev-attention-panel"><h2>Attention Required</h2><p>Highest leverage work first.</p>{ranked.map((pull, index) => <button key={pull.number} className="dev-attention-item" onClick={() => setSelected(pull.number)}><span className="dev-rank">{index + 1}</span><div><strong>#{pull.number} · {statusLabel(pull.status)}</strong><span>{pull.title}</span><small>blocks {pull.downstreamCount} · score {pull.bottleneckScore}</small><em>→ {nextAction(pull)}</em></div></button>)}</aside>
      </div>}

      {snapshot && tab === "commits" && <section className="dev-main-panel"><div className="dev-section-heading"><div><h2>Commit Graph</h2><p>Recent main and open-PR commits, capped at 100 nodes.</p></div></div><CommitGraph commits={snapshot.commits} /></section>}

      {selectedPull && <div className="dev-drawer-backdrop" onClick={() => setSelected(null)}><aside className="dev-drawer" role="dialog" aria-label={`PR #${selectedPull.number} details`} onClick={(event) => event.stopPropagation()}><button className="dev-drawer-close" onClick={() => setSelected(null)}>×</button><span className={`dev-status dev-status-${selectedPull.status.toLowerCase().replace("_", "-")}`}>{statusLabel(selectedPull.status)}{selectedPull.stale ? ` · STALE ${selectedPull.staleDays}d` : ""}</span><h2>#{selectedPull.number} {selectedPull.title}</h2><a href={selectedPull.url} target="_blank" rel="noreferrer">Open on GitHub ↗</a><dl><dt>Author</dt><dd>{selectedPull.author}</dd><dt>Branch</dt><dd>{selectedPull.head} → {selectedPull.base}</dd><dt>Head SHA</dt><dd><code>{selectedPull.headSha.slice(0, 12)}</code></dd><dt>Updated</dt><dd>{new Date(selectedPull.updatedAt).toLocaleString()}</dd><dt>Depends on</dt><dd>{selectedPull.dependencies.length ? selectedPull.dependencies.map((item) => `#${item}`).join(", ") : "—"}</dd><dt>Downstream</dt><dd>{selectedPull.downstream.length ? selectedPull.downstream.map((item) => `#${item}`).join(", ") : "—"}</dd><dt>Review</dt><dd>{selectedPull.approvalCount} approval(s){selectedPull.changesRequested.length ? ` · ${selectedPull.changesRequested.length} changes requested` : ""}</dd></dl><h3>Why blocked</h3>{selectedPull.blockers.length ? <ul>{selectedPull.blockers.map((item) => <li key={item}>{item}</li>)}</ul> : <p>No hard blocker detected.</p>}{selectedPull.changesRequested[0]?.body && <div className="dev-review-note"><strong>Latest change request</strong><p>{selectedPull.changesRequested[0].body.slice(0, 420)}</p></div>}<h3>Checks</h3><ul className="dev-check-list">{selectedPull.checks.length ? selectedPull.checks.map((check) => <li key={`${check.name}-${check.url}`}><span>{check.name}</span><strong>{check.status === "completed" ? check.conclusion ?? "completed" : check.status}</strong></li>) : <li>No check-runs reported.</li>}</ul></aside></div>}
    </main>
  );
}
export default DevDashboardPage;
