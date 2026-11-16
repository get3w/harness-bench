/** Launch a build, never the installed personal app. Driver assertions are product-specific. */
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const scenarios = ['selection_binding', 'stream_final_consistency', 'abort_clear_queue', 'permission_deny', 'question_cancel', 'resume_after_restart', 'concurrent_isolation', 'attachment_roundtrip', 'mcp_tool_result', 'browser_stop', 'computer_takeover'];
export async function run({ executablePath, entry, output, harness, driverPath }) {
  if (!entry || !driverPath || !output) throw new Error('entry, driverPath, output required');
  if (executablePath && /\.app\/Contents\/MacOS\//.test(executablePath)) throw new Error('Use a development Electron executable, not an installed app');
  const { _electron: electron } = await import('playwright');
  const driver = await import(pathToFileURL(resolve(driverPath)));
  const profile = await mkdtemp(join(tmpdir(), 'get3w-bench-'));
  await mkdir(output, { recursive: true });
  const app = await electron.launch({ executablePath, args: [resolve(entry)], env: { ...process.env, GET3W_ELECTRON_USERDATA: join(profile, 'electron'), GET3W_DATA_DIR: join(profile, 'data') } });
  const rows = [];
  try {
    const page = await app.firstWindow();
    for (const scenario of scenarios) {
      if (!driver[scenario]) { rows.push({ scenario, status: 'blocked', detail: 'product assertion unavailable' }); continue; }
      try {
        const evidence = await driver[scenario]({ app, page, harness, profile });
        if (!evidence || !Array.isArray(evidence.assertions) || !evidence.assertions.length || evidence.assertions.some(a => a.passed !== true)) throw new Error('missing or failed contract assertions');
        const screenshot = join(resolve(output), `${scenario}.png`);
        await page.screenshot({ path: screenshot });
        rows.push({ scenario, harness, status: 'passed', execution_mode: 'real_desktop', evidence: { ...evidence, screenshot } });
      } catch (error) { rows.push({ scenario, harness, status: 'failed', detail: String(error) }); }
    }
  } finally { await app.close(); }
  await writeFile(join(output, 'contracts.json'), JSON.stringify(rows, null, 2));
  return rows;
}
