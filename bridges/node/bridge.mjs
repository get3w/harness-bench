/** Original bench protocol host. Drivers must use real Get3W APIs, never spawn a native fallback. */
import http from 'node:http';
import { pathToFileURL } from 'node:url';
import { randomUUID, timingSafeEqual } from 'node:crypto';
import { resolve } from 'node:path';

const token = process.env.GET3W_BENCH_TOKEN;
if (!token || !process.env.GET3W_BENCH_DRIVER) throw new Error('GET3W_BENCH_TOKEN and GET3W_BENCH_DRIVER required');
const driver = await import(pathToFileURL(resolve(process.env.GET3W_BENCH_DRIVER)));
const sessions = new Map();
const reply = (res, status, body) => {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
};
const server = http.createServer(async (req, res) => {
  try {
    const supplied = Buffer.from((req.headers.authorization || '').replace(/^Bearer /, ''));
    const expected = Buffer.from(token);
    if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) return reply(res, 401, { error: 'unauthorized' });
    const url = new URL(req.url, 'http://localhost');
    if (req.method === 'GET' && url.pathname === '/v1/info') return reply(res, 200, { protocol_version: 1, runtimes: await driver.runtimes() });
    let body = '';
    for await (const chunk of req) {
      body += chunk;
      if (Buffer.byteLength(body) > 16 * 1024 * 1024) throw new Error('body too large');
    }
    const input = body ? JSON.parse(body) : {};
    if (req.method === 'POST' && url.pathname === '/v1/contracts') {
      const result = driver.contract ? await driver.contract(input) : { scenario: input.scenario, status: 'blocked', detail: 'Desktop driver unavailable' };
      return reply(res, 200, result);
    }
    if (req.method === 'POST' && url.pathname === '/v1/sessions') {
      const session = await driver.create(input);
      const id = randomUUID();
      sessions.set(id, session);
      return reply(res, 201, { session_id: id, identity: session.identity, environment_digest: session.environmentDigest });
    }
    const match = /^\/v1\/sessions\/([\w-]+)(?:\/(turns|events|abort))?$/.exec(url.pathname);
    const session = match && sessions.get(match[1]);
    if (!session) return reply(res, 404, { error: 'unknown session' });
    if (req.method === 'DELETE' && !match[2]) {
      await session.close(); sessions.delete(match[1]); return reply(res, 200, {});
    }
    if (req.method === 'POST' && match[2] === 'turns') return reply(res, 200, await session.turn(input));
    if (req.method === 'POST' && match[2] === 'abort') return reply(res, 200, await session.abort(input));
    if (req.method === 'GET' && match[2] === 'events') return reply(res, 200, await session.events(url.searchParams.get('after')));
    if (req.method === 'GET' && !match[2]) return reply(res, 200, await session.snapshot());
    return reply(res, 404, { error: 'unsupported route' });
  } catch (error) { reply(res, 409, { error: String(error) }); }
});
server.listen(Number(process.env.GET3W_BENCH_PORT || 8790), '127.0.0.1', () => process.stdout.write('Bench bridge listening on loopback\n'));
async function stop() {
  server.close();
  await Promise.allSettled([...sessions.values()].map(session => session.close()));
}
process.once('SIGTERM', () => stop().finally(() => process.exit()));
process.once('SIGINT', () => stop().finally(() => process.exit()));
