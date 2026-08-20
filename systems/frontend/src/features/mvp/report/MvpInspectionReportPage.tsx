import { AlertTriangle, ArrowLeft, Database, FileText, Gauge, History, ShieldCheck, Wrench } from "lucide-react";

export function MvpInspectionReportPage({
  onBackToOverview,
}: {
  onBackToOverview: () => void;
}) {
  return (
    <div className="mvp-page mvp-static-report-page" data-testid="mvp-static-report">
      <div className="mvp-report-toolbar">
        <button type="button" className="mvp-button secondary" onClick={onBackToOverview}><ArrowLeft size={14} />Overview</button>
        <div><span className="mvp-report-mode mode-template-fallback">Static report</span><strong>Map-report UI prototype embedded as a side tab.</strong></div>
        <button type="button" className="mvp-button secondary"><FileText size={15} />Export draft</button>
      </div>

      <section className="mvp-static-report-shell">
        <header className="mvp-static-report-topbar">
          <div>
            <span>Inspection report</span>
            <h1>Compressor Station 03 predictive maintenance report</h1>
            <p>Static English report view adapted from the map-report UI prototype. This tab does not parse raw producer payloads or import prototype runtime code.</p>
          </div>
          <aside className="mvp-static-report-meta">
            <span>Report status</span>
            <strong>Human review requested</strong>
            <small>Observed at 2026-08-29 23:00 KST</small>
          </aside>
        </header>

        <section className="mvp-static-kpis" aria-label="Report summary">
          <article><Gauge size={18} /><span>24h risk</span><strong>82.4%</strong><small>Warning threshold 70%</small></article>
          <article className="warm"><AlertTriangle size={18} /><span>Primary signal</span><strong>Rotation drop</strong><small>420.1 rpm, below normal band</small></article>
          <article><Database size={18} /><span>Evidence mode</span><strong>Static prototype</strong><small>No runtime dependency</small></article>
          <article className="hold"><ShieldCheck size={18} /><span>Decision boundary</span><strong>Review only</strong><small>No automatic shutdown command</small></article>
        </section>

        <div className="mvp-static-report-grid">
          <main className="mvp-static-report-main">
            <section className="mvp-static-panel mvp-static-manager-brief">
              <header className="mvp-static-panel-heading">
                <div><span>Manager brief</span><h2>Inspection request summary</h2></div>
                <strong className="mvp-static-status critical">Critical</strong>
              </header>
              <p className="mvp-static-lead">The compressor shows a high probability of failure within the next 24 hours. The report requests field inspection of the motor-drive-pump assembly before issuing any production stop decision.</p>
              <div className="mvp-static-decision-stack">
                <article><Wrench size={17} /><div><strong>Record field inspection</strong><span>Log vibration, rotation, and belt tension observations in Operations.</span></div></article>
                <article><ShieldCheck size={17} /><div><strong>Keep decision human-reviewed</strong><span>The recommended action is a review request, not an automated equipment command.</span></div></article>
              </div>
            </section>

            <section className="mvp-static-panel">
              <header className="mvp-static-panel-heading compact">
                <div><span>Target equipment</span><h2>Compressor assembly focus areas</h2></div>
              </header>
              <div className="mvp-static-equipment-sketch">
                <div>
                  <strong>CMP-S03-L03-01 · Rotary compressor</strong>
                  <p>Prototype-style equipment sketch highlights the components that need on-site inspection. The markers are static report annotations.</p>
                  <ol className="mvp-static-sketch-legend">
                    <li><b>1</b><span>Motor to drive coupling: check rotation loss and belt tension.</span></li>
                    <li><b>2</b><span>Drive to pump shaft: inspect vibration transfer and alignment.</span></li>
                    <li><b>3</b><span>Pump outlet path: confirm pressure stability before escalation.</span></li>
                  </ol>
                </div>
                <div className="mvp-static-compressor-visual" aria-label="Static compressor inspection diagram">
                  <span className="vibration-zone" />
                  <span className="motor">MOTOR</span>
                  <span className="shaft drive">DRIVE</span>
                  <span className="pump">PUMP</span>
                  <span className="valve">OUTLET<br />VALVE</span>
                  <span className="tank">AIR TANK</span>
                  <span className="power-unit">PWR</span>
                  <span className="pipe pipe-1" />
                  <span className="pipe pipe-2" />
                  <span className="pipe pipe-3" />
                  <span className="pipe pipe-4" />
                  <b className="callout loc-motor-drive">1</b>
                  <b className="callout loc-drive-pump">2</b>
                  <b className="callout loc-pump-valve">3</b>
                </div>
              </div>
              <div className="mvp-static-target-list">
                <article><b>1</b><i>R</i><div><strong>Rotation mean</strong><p>Current value is below the expected operating band.</p><code>sensor.rotation_raw</code></div><span className="target-severity critical">High</span></article>
                <article><b>2</b><i>V</i><div><strong>Vibration mean</strong><p>Vibration is above baseline and should be checked at the drive-pump interface.</p><code>sensor.vibration_raw</code></div><span className="target-severity high">Med</span></article>
              </div>
            </section>
          </main>

          <aside className="mvp-static-report-side">
            <section className="mvp-static-panel">
              <header className="mvp-static-panel-heading compact">
                <div><span>Sensor evidence</span><h2>Reference values</h2></div>
              </header>
              <div className="mvp-static-sensor-window">
                <strong>Six-hour inspection window</strong>
                <p>Values are static prototype content for UI evaluation only.</p>
              </div>
              <div className="mvp-static-sensor-table">
                <div><code>rotation_raw</code><strong>420.1 rpm</strong><span>Below baseline</span><small>Normal band 448-462 rpm</small></div>
                <div><code>vibration_raw</code><strong>39.8 mm/s</strong><span>Above baseline</span><small>Normal band 35.4-37.8 mm/s</small></div>
                <div><code>risk_score</code><strong>82.4%</strong><span>Above warning threshold</span><small>Threshold 70%</small></div>
                <div><code>confidence</code><strong>0.78</strong><span>Moderate confidence</span><small>Requires field confirmation</small></div>
              </div>
            </section>

            <section className="mvp-static-panel">
              <header className="mvp-static-panel-heading compact">
                <div><span>Evidence trace</span><h2>Grounding chain</h2></div>
              </header>
              <div className="mvp-static-evidence-list">
                <article><span>Model factor</span><strong>Rotation drop contributed 43% of the risk score.</strong><p>The report treats this as a signal to inspect, not as confirmed root cause.</p></article>
                <article><span>Maintenance context</span><strong>Recent belt tension adjustment is relevant to the inspection scope.</strong><p>The static report keeps this as provenance context and avoids creating a work order.</p></article>
              </div>
              <dl className="mvp-static-trace-meta">
                <div><dt>Source boundary</dt><dd>Static map-report UI reference</dd></div>
                <div><dt>Runtime dependency</dt><dd>None</dd></div>
              </dl>
            </section>

            <section className="mvp-static-panel">
              <header className="mvp-static-panel-heading compact">
                <div><span>History</span><h2>Recent inspection timeline</h2></div>
                <History size={17} />
              </header>
              <div className="mvp-static-history-list">
                <article><time>2026-08-29 23:00</time><strong>Predictive alarm</strong><p>24h risk exceeded warning threshold.</p></article>
                <article><time>2026-08-12 10:30</time><strong>Scheduled maintenance</strong><p>Belt tension adjusted and drive lubrication completed.</p></article>
                <article><time>2026-07-28 17:30</time><strong>Failure record</strong><p>Prior stop event recorded; root cause is not asserted in this UI.</p></article>
              </div>
            </section>
          </aside>
        </div>
      </section>
    </div>
  );
}
