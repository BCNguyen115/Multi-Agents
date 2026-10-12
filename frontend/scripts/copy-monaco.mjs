// Copies Monaco's runtime (public/monaco/vs) next to the app, so the diff editor loads from THIS origin (the CSP allows no CDN).
// Run by npm before `dev` and `build`; the copy is generated, not committed (.gitignore).
import { cpSync, existsSync, mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const source = join(root, 'node_modules', 'monaco-editor', 'min', 'vs');
const target = join(root, 'public', 'monaco', 'vs');

if (!existsSync(source)) {
  console.error(`copy-monaco: ${source} not found: run npm install first`);
  process.exit(1);
}
if (!existsSync(join(target, 'loader.js'))) {
  rmSync(target, { recursive: true, force: true });
  mkdirSync(dirname(target), { recursive: true });
  cpSync(source, target, { recursive: true });
}
console.log('copy-monaco: public/monaco/vs ready');
