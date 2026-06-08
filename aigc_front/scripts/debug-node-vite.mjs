// #region agent log
import { appendFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const LOG = new URL('../../debug-56b815.log', import.meta.url);
const log = (hypothesisId, message, data) => {
  const entry = JSON.stringify({
    sessionId: '56b815',
    runId: 'diagnostic',
    hypothesisId,
    location: 'scripts/debug-node-vite.mjs',
    message,
    data,
    timestamp: Date.now(),
  });
  appendFileSync(LOG, entry + '\n');
  fetch('http://127.0.0.1:7743/ingest/6dfa21d3-786b-4d8e-a2df-0044808489e2', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': '56b815' },
    body: entry,
  }).catch(() => {});
};
// #endregion

// Hypothesis A: Node.js version too old for Vite 6
log('A', 'node_version', {
  version: process.version,
  major: process.versions.node.split('.')[0],
});

// Hypothesis B: node:fs/promises lacks 'constants' export on this Node
let constantsExport = 'unknown';
try {
  const fsp = await import('node:fs/promises');
  constantsExport = 'constants' in fsp ? 'present' : 'missing';
  log('B', 'fs_promises_constants', { constantsExport, fspKeys: Object.keys(fsp).slice(0, 10) });
} catch (e) {
  log('B', 'fs_promises_import_error', { error: e.message });
}

// Hypothesis C: installed Vite requires newer Node than current
try {
  const require = createRequire(import.meta.url);
  const vitePkg = require('../node_modules/vite/package.json');
  log('C', 'vite_engines', {
    viteVersion: vitePkg.version,
    engines: vitePkg.engines,
    nodeSatisfies: (() => {
      const req = vitePkg.engines?.node;
      if (!req) return 'unknown';
      const major = parseInt(process.versions.node.split('.')[0], 10);
      return major >= 18;
    })(),
  });
} catch (e) {
  log('C', 'vite_pkg_read_error', { error: e.message });
}

// Hypothesis D: which node binary is used
log('D', 'node_exec', {
  execPath: process.execPath,
  platform: process.platform,
  arch: process.arch,
});

// Hypothesis E: esbuild/rollup also require Node 18+
try {
  const require = createRequire(import.meta.url);
  const esbuildPkg = require('../node_modules/esbuild/package.json');
  const rollupPkg = require('../node_modules/rollup/package.json');
  log('E', 'peer_engines', {
    esbuild: { version: esbuildPkg.version, engines: esbuildPkg.engines },
    rollup: { version: rollupPkg.version, engines: rollupPkg.engines },
  });
} catch (e) {
  log('E', 'peer_engines_error', { error: e.message });
}

console.log('Diagnostic complete. Node:', process.version);
