// Copies the DuckDB-WASM bundles next to the app (public/duckdb/), so the browser loads them from THIS origin instead of a
// third-party CDN (cdn.jsdelivr.net): no code from outside the deployment runs in the page, and the CSP can say 'self'.
// Run by npm before `dev` and `build` (the "predev" / "prebuild" hooks); the copies are generated, not committed (.gitignore).
import { copyFileSync, existsSync, mkdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const source = join(root, 'node_modules', '@duckdb', 'duckdb-wasm', 'dist');
const target = join(root, 'public', 'duckdb');
const files = ['duckdb-mvp.wasm', 'duckdb-eh.wasm', 'duckdb-browser-mvp.worker.js', 'duckdb-browser-eh.worker.js'];

if (!existsSync(source)) {
  console.error(`copy-duckdb: ${source} not found: run npm install first`);
  process.exit(1);
}
mkdirSync(target, { recursive: true });
for (const file of files) {
  const from = join(source, file);
  const to = join(target, file);
  if (!existsSync(from)) {
    console.error(`copy-duckdb: ${from} is missing: the installed @duckdb/duckdb-wasm has a different layout`);
    process.exit(1);
  }
  if (!existsSync(to) || statSync(to).size !== statSync(from).size) copyFileSync(from, to); // big files: skip when already there
}
console.log(`copy-duckdb: ${files.length} files in public/duckdb`);
