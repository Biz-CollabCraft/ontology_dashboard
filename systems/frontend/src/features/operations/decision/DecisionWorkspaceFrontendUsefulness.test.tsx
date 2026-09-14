import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyAssetDetailViewModel, composeEventDetail } from "../api/operationsAdapters";
import type { OperationsEvent } from "../api/operationsContracts";
import { decisionDetailFixture } from "../../../../e2e/fixtures/decision-detail.fixture";
import { decisionProposalFixture } from "../../../../e2e/fixtures/decision-proposal.fixture";
import { DecisionConditions, DecisionProposalPanel } from "./DecisionProposalPanel";
import { DECISION_ACTION_LABELS, type DecisionProposalState } from "./decisionProposalAdapter";

const scope = { projectId: "p", workspaceId: "w", eventId: "event-1", assetId: "asset-1" };
const roles = ["process_manager"];
const permissions = ["events.decision"];

type FrontendCue = {
  name: string;
  manualLookupWhenMissing: string;
  present: (text: string) => boolean;
};

const FRONTEND_STRUCTURE_CUES: FrontendCue[] = [
  {
    name: "관측 시점",
    manualLookupWhenMissing: "추천이 어느 관측 기준인지 별도 근거 패널에서 다시 확인해야 함",
    present: text => text.includes("선택한 관측 시점"),
  },
  {
    name: "작업 생성 없음",
    manualLookupWhenMissing: "추천 확인과 작업 생성이 분리되는지 사용자가 추정해야 함",
    present: text => text.includes("작업 생성 없이"),
  },
  {
    name: "조회 단계",
    manualLookupWhenMissing: "어떤 운영 정보를 확인했는지 별도 로그를 찾아야 함",
    present: text => text.includes("설비 상태 확인") || text.includes("설비 위험 상태 확인"),
  },
  {
    name: "확인됨/미확인/충돌 분리",
    manualLookupWhenMissing: "확정 사실과 미확정 정보, 충돌을 사람이 다시 분류해야 함",
    present: text => ["확인됨", "미확인", "충돌"].every(label => text.includes(label)),
  },
  {
    name: "생산 영향 비교값",
    manualLookupWhenMissing: "정지시간 가정 차이를 원문 근거에서 다시 계산해야 함",
    present: text => text.includes("생산 영향 산정: 120분") && text.includes("예상 정비 작업: 180분"),
  },
  {
    name: "데이터 출처",
    manualLookupWhenMissing: "판단에 사용된 출처를 별도 근거 목록에서 대조해야 함",
    present: text => text.includes("데이터 출처") && text.includes("판단에 사용한 데이터"),
  },
  {
    name: "추천/대안 구분",
    manualLookupWhenMissing: "가능 액션의 우선순위를 사람이 직접 비교해야 함",
    present: text => text.includes("추천") && text.includes("대안"),
  },
  {
    name: "담당자 검토 경계",
    manualLookupWhenMissing: "추천을 누르는 행위가 승인인지 검토 진입인지 헷갈릴 수 있음",
    present: text => text.includes("담당자 검토 후 요청"),
  },
];

function setup() {
  const event = { eventId: scope.eventId, assetId: scope.assetId, datasetVersionId: "dataset-1" } as OperationsEvent;
  const detail = applyAssetDetailViewModel(
    composeEventDetail({ event, evidence: null, report: null, activity: null }),
    decisionDetailFixture(event.eventId, event.assetId, event.datasetVersionId),
  );
  const state = decisionProposalFixture({ ...scope, snapshotBasis: detail.snapshotBasis });
  if (state.status !== "ready") throw new Error("fixture");
  Object.assign(state.session.proposal!.conflicts[0], {
    text: "생산 영향 계산의 정지시간과 정비 작업 예상시간이 다릅니다.",
    comparison: { planningMinutes: 120, maintenanceMinutes: 180 },
  });
  return { detail, state };
}

function LegacyBriefingOnlyPanel({ state }: { state: DecisionProposalState }) {
  const proposal = state.status === "ready" ? state.session.proposal : null;
  const recommended = proposal?.recommended_action;
  return <section aria-label="단순 판단 요약">
    <h2>다음 판단</h2>
    <p>{proposal?.reasoning_summary ?? "판단 요약을 확인하고 있습니다."}</p>
    {recommended && <button>{DECISION_ACTION_LABELS[recommended]}</button>}
  </section>;
}

function score(text: string) {
  const passed = FRONTEND_STRUCTURE_CUES.filter(cue => cue.present(text));
  return {
    passed: passed.length,
    total: FRONTEND_STRUCTURE_CUES.length,
    rate: passed.length / FRONTEND_STRUCTURE_CUES.length,
    missingManualLookups: FRONTEND_STRUCTURE_CUES.filter(cue => !cue.present(text)).map(cue => cue.manualLookupWhenMissing),
  };
}

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("Decision Workspace frontend structure usefulness (fixture-backed)", () => {
  it("preserves more review cues than a briefing-only action surface", async () => {
    const { detail, state } = setup();

    await act(async () => root.render(<LegacyBriefingOnlyPanel state={state} />));
    const briefingOnly = score(host.textContent ?? "");

    await act(async () => root.render(<>
      <DecisionConditions state={state} detail={detail} />
      <DecisionProposalPanel state={state} detail={detail} roles={roles} permissions={permissions} refreshing={false} onReview={vi.fn()} />
    </>));
    const workspace = score(host.textContent ?? "");

    expect(briefingOnly).toMatchObject({ passed: 0, total: 8, rate: 0 });
    expect(briefingOnly.missingManualLookups).toHaveLength(8);
    expect(workspace).toMatchObject({ passed: 8, total: 8, rate: 1 });
    expect(workspace.missingManualLookups).toEqual([]);
  });
});
