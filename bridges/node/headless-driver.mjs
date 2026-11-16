/** Uses current Get3W HeadlessThreadClient. Lifecycle/identity comes from a trusted isolated launcher. */
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { writeFile } from 'node:fs/promises';

if (!process.env.GET3W_BENCH_LAUNCHER || !process.env.GET3W_HEADLESS_MODULE) {
  throw new Error('Set GET3W_BENCH_LAUNCHER and GET3W_HEADLESS_MODULE to built Get3W modules');
}
const launcher = await import(pathToFileURL(resolve(process.env.GET3W_BENCH_LAUNCHER)));
const { createHeadlessThreadClient } = await import(pathToFileURL(resolve(process.env.GET3W_HEADLESS_MODULE)));
export const runtimes = () => launcher.runtimes();
export async function create(input) {
  if (input.harness !== 'opencode') throw new Error('Current Get3W client only implements OpenCode; no native fallback');
  // Launcher must start an isolated real server/engine in the supplied workspace,
  // configure the disposable model gateway, and attest measured runtime identity.
  const runtime = await launcher.start(input);
  try {
    if (runtime.workspace !== input.workspace || runtime.modelEndpoint !== input.model.endpoint || runtime.isolated !== true) throw new Error('launcher failed isolation/gateway binding');
    const client = createHeadlessThreadClient(runtime.clientOptions);
    const thread = await client.createThread({ title: `bench:${input.trial_id}`, model: runtime.model });
    let acceptance;
    let outcome;
    let pending;
    let aborted = false;
    const log = [];
    const seen = new Set();
    return {
      identity: runtime.identity,
      environmentDigest: runtime.environmentDigest,
      async turn(turn) {
        if (seen.has(turn.request_id)) return { accepted: true, duplicate: true };
        if (pending) throw new Error('a turn is already active');
        seen.add(turn.request_id);
        acceptance = await client.sendTurn(thread.id, { prompt: turn.text, model: runtime.model, messageId: `msg_${turn.request_id.replaceAll('-', '')}` });
        pending = client.waitForThread(thread.id, { timeoutMs: input.budget.timeout_sec * 1000, since: acceptance }).then(result => { outcome = result; }).catch(error => { outcome = { outcome: 'failed', error: String(error) }; });
        return { accepted: true };
      },
      async events(after) {
        const snapshot = await client.getThreadSnapshot(thread.id);
        log.push({ type: 'get3w_snapshot', snapshot });
        await writeFile(`${input.run_directory}/trace/get3w-snapshots.json`, JSON.stringify(log));
        const start = Number(after || 0);
        if (!Number.isInteger(start) || start < 0 || start > log.length) throw new Error('invalid event cursor');
        return { events: log.slice(start), cursor: String(log.length) };
      },
      async snapshot() {
        if (!outcome) {
          const waiting = await client.getThreadWaitingFor(thread.id);
          return { status: waiting ? `waiting_${waiting}` : 'running' };
        }
        const transcript = await client.exportTranscript(thread.id);
        await writeFile(`${input.run_directory}/trace/get3w-transcript.json`, JSON.stringify(transcript));
        return { status: aborted ? 'aborted' : ({ settled: 'completed', failed: 'model_error', timeout: 'timeout', aborted: 'aborted' }[outcome.outcome] || 'protocol_error'), trace_complete: !outcome.error };
      },
      async abort() { aborted = true; await client.abortThread(thread.id); await pending; return { accepted: true }; },
      async close() {
        try { if (pending && !outcome) { await client.abortThread(thread.id); await pending; } }
        finally { await runtime.stop(); }
      },
    };
  } catch (error) { await runtime.stop(); throw error; }
}
