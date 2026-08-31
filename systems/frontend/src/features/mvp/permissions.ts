const AGENT_REVIEW_MATERIALIZE_PERMISSION = "agent.review.materialize";

export function canMaterializeAgentReviewSummary(
  permissions: readonly string[] | null | undefined,
): boolean {
  return Boolean(permissions?.includes(AGENT_REVIEW_MATERIALIZE_PERMISSION));
}
