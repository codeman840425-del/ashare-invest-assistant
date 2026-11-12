/* B-03: offline frontend consumer checks. Does not start a server or change frontend files. */
'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const Module = require('node:module');

const [bundleDir, frontendDir, nodeModules, reportPath] = process.argv.slice(2);
if (!bundleDir || !frontendDir || !nodeModules || !reportPath) {
  throw new Error('usage: node b03_frontend_dry.cjs BUNDLE FRONTEND NODE_MODULES REPORT');
}
const ts = require(path.resolve(nodeModules, 'typescript/lib/typescript.js'));
const frontend = fs.realpathSync(frontendDir);
const manifest = JSON.parse(fs.readFileSync(path.join(bundleDir, 'manifest.json'), 'utf8'));
assert.equal(manifest.synthetic, true);
const bundle = {};
for (const [name, digest] of Object.entries(manifest.files)) {
  assert.match(name, /^(bars|financials|fund-flows|factors|announcements)\.json$/);
  const raw = fs.readFileSync(path.join(bundleDir, name));
  assert.equal(crypto.createHash('sha256').update(raw).digest('hex'), digest);
  bundle[name.slice(0, -5)] = JSON.parse(raw.toString('utf8'));
}
assert.equal(Object.keys(bundle).length, 5);
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'b03-types-'));
let serial = 0;
function check(entries) {
  const api = path.join(frontend, 'src/api').replaceAll('\\', '/');
  const lines = [
    `import type {BarsResponse} from ${JSON.stringify(api + '/types')};`,
    `import type {FinancialsResponse,FundFlowsResponse,FactorsResponse,AnnouncementsResponse} from ${JSON.stringify(api + '/marketTypes')};`,
  ];
  entries.forEach(([resource, body], index) => {
    lines.push(`const response${index}: ${manifest.frontend_types[resource]} = ${JSON.stringify(body, null, 2)};`);
  });
  const filename = path.join(temporary, `case-${serial++}.ts`);
  fs.writeFileSync(filename, lines.join('\n'), 'utf8');
  const program = ts.createProgram([filename], {
    noEmit: true, strict: true, skipLibCheck: true, types: [],
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
  });
  return ts.getPreEmitDiagnostics(program).map(d => ({
    code: d.code, message: ts.flattenDiagnosticMessageText(d.messageText, '\n'),
  }));
}
const full = [];
const populated = [];
for (const [resource, cases] of Object.entries(bundle)) {
  for (const entry of Object.values(cases)) {
    full.push([resource, entry.response]);
    if (entry.response.items.length) populated.push([resource, entry.response]);
  }
}
assert.deepEqual(check(populated), []);
const allDiagnostics = check(full);
const missingTimeCount = full.filter(([, body]) => body.data_as_of === null).length;
assert.ok(allDiagnostics.length === 0 || allDiagnostics.length === missingTimeCount);
assert.ok(allDiagnostics.every(d => d.code === 2322 && d.message.includes("Type 'null' is not assignable to type 'string'")));
const numeric = structuredClone(bundle.financials.stock.response);
numeric.items[0].revenue = 1.25;
assert.ok(check([['financials', numeric]]).some(d => d.code === 2322));
const missing = structuredClone(bundle.financials.stock.response);
delete missing.items[0].debt_ratio_pct;
assert.ok(check([['financials', missing]]).some(d => d.message.includes('debt_ratio_pct')));

// Reuse the actual frontend mock constructors. The TS loader lives only in this process.
const previous = Module._extensions['.ts'];
Module._extensions['.ts'] = function (module, filename) {
  if (!fs.realpathSync(filename).startsWith(frontend + path.sep)) throw new Error('TS mock import left frontend');
  const result = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022},
    fileName: filename,
  });
  module._compile(result.outputText, filename);
};
try {
  const market = require(path.join(frontend, 'src/mocks/marketFixtures.ts'));
  const stock = require(path.join(frontend, 'src/mocks/fixtures.ts'));
  const actual = {
    bars: stock.dailyBars('600000.SH'),
    financials: market.financials('600000.SH', 2),
    'fund-flows': market.fundFlows('600000.SH', 2),
    factors: market.factors('600000.SH'),
    announcements: {...market.announcementsMeta(), items: market.announcements('600000.SH'), next_cursor: null},
  };
  for (const [resource, response] of Object.entries(actual)) {
    assert.ok(response && response.items.length, `empty actual mock: ${resource}`);
    const seeded = bundle[resource].stock.response;
    assert.deepEqual(Object.keys(seeded).sort(), Object.keys(response).sort(), `response keys: ${resource}`);
    assert.deepEqual(Object.keys(seeded.items[0]).sort(), Object.keys(response.items[0]).sort(), `item keys: ${resource}`);
  }
  fs.writeFileSync(reportPath, JSON.stringify({
    synthetic: true, external_requests: 0, application_routes_registered: 0,
    cases: full.length, populated_types_passed: populated.length,
    actual_mock_resources_matched: Object.keys(actual),
    numeric_decimal_mutation_rejected: true, missing_required_field_mutation_rejected: true,
    full_type_check: allDiagnostics.length ? 'blocked_by_existing_nullable_timestamp_type' : 'pass',
    empty_data_cases: missingTimeCount,
    known_nullable_timestamp_errors: allDiagnostics.length, diagnostics: allDiagnostics,
    frontend_type_hashes: Object.fromEntries(['types.ts', 'marketTypes.ts', 'enums.ts'].map(name => [
      name, crypto.createHash('sha256').update(fs.readFileSync(path.join(frontend, 'src/api', name))).digest('hex'),
    ])),
    typescript_version: ts.version,
  }, null, 2) + '\n', 'utf8');
  console.log(JSON.stringify({populated_types_passed: populated.length, mock_resources_matched: 5, known_nullable_timestamp_errors: allDiagnostics.length}));
} finally {
  if (previous) Module._extensions['.ts'] = previous;
  else delete Module._extensions['.ts'];
  // No removal of computed paths: leave the small compiler inputs in the OS temp directory.
}
