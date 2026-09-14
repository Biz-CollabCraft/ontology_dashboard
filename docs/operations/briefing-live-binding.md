# 10-second observation / briefing binding fix

- FILE event IDs supply their own dataset/run identity in the shared briefing UI; the current dashboard run cannot overwrite an older work request's identity.
- Backend exact-event lookup can read retained complete ticks from permitted generator roots. It rejects a mismatched dataset, a different asset's observation, traversal IDs, and incomplete equipment ticks.
- Sensor polling no longer remounts the briefing for each FILE observation. Generation/read-back keeps the same event and displayed observation time. A changed work state, asset, role, or run still resets the view.
- When newer observations arrive, the existing briefing is labelled as retaining its original basis. Manual regeneration uses the latest props. No automatic paid generation is introduced.
- Rate-limit errors return HTTP 429 and Retry-After instead of an unhandled 500. The existing limit is not increased or disabled.
- Validation: 13 frontend tests including in-flight refresh, 2 backend binding/error tests; frontend build passed. The retained demo-runtime-001 event for CNC-S03-L04-03 resolves while demo-10s-live is active, with inspection and production coordination evidence intact.
- No workflow rows or stored summaries were deleted. Actual model generation is not part of these non-billable regression checks.
