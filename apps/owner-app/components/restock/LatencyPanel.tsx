'use client';
// ?debug=1 only: client latency marks per turn (ms, relative to the first mark of each turn). No transcript text.
import { MARK_ORDER, span, useLatency } from '@/lib/latency';

export function LatencyPanel() {
  const utts = useLatency();
  return (
    <section className="card debug-panel" aria-label="Latency (debug)">
      <div className="row between"><b>Latency marks (ms)</b><span className="faint">{utts.length} turns</span></div>
      <table>
        <thead>
          <tr><th style={{ textAlign: 'left' }}>turn</th><th>src</th><th>1st partial</th><th>end→final</th><th>final→sent</th><th>sent→applied</th><th>applied→rendered</th><th>end→rendered</th><th>server total</th><th>extract</th><th>apply</th></tr>
        </thead>
        <tbody>
          {utts.map((u) => {
            const endish = u.marks.utterance_end !== undefined ? 'utterance_end' : u.marks.final_transcript !== undefined ? 'final_transcript' : 'turn_sent';
            return (
              <tr key={u.id}>
                <td style={{ textAlign: 'left' }}>{u.id.slice(-5)}</td>
                <td>{u.engine}</td>
                <td>{span(u, 'speech_start', 'first_partial') ?? '–'}</td>
                <td>{span(u, 'utterance_end', 'final_transcript') ?? '–'}</td>
                <td>{span(u, 'final_transcript', 'turn_sent') ?? '–'}</td>
                <td>{span(u, 'turn_sent', 'turn_applied') ?? '–'}</td>
                <td>{span(u, 'turn_applied', 'draft_rendered') ?? '–'}</td>
                <td>{span(u, endish, 'draft_rendered') ?? '–'}</td>
                <td>{u.server?.total ?? '–'}</td>
                <td>{u.server?.extract ?? '–'}</td>
                <td>{u.server?.apply ?? '–'}</td>
              </tr>
            );
          })}
          {first0(utts.length)}
        </tbody>
      </table>
      <pre id="latency-json" hidden>{JSON.stringify(utts.map((u) => ({ id: u.id, engine: u.engine, server: u.server, chars: u.chars, marks: Object.fromEntries(Object.entries(u.marks).map(([k, v]) => [k, Math.round((v as number) - (MARK_ORDER.map((m) => u.marks[m]).find((x) => x !== undefined) as number))])) })))}</pre>
    </section>
  );
}
function first0(n: number) { return n ? null : <tr><td colSpan={11} style={{ textAlign: 'left' }}>No turns yet.</td></tr>; }
