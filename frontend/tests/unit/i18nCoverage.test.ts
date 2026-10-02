import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';
import { en } from '../../lib/locales/en';
import { vi } from '../../lib/locales/vi';

const slots = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort().join();

describe('interface dictionaries', () => {
  it('have the same keys, and each key the same {placeholders}, in Vietnamese and English', () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(vi).sort());
    for (const key of Object.keys(vi) as (keyof typeof vi)[]) {
      expect(slots(en[key]), key).toBe(slots(vi[key]));
      expect(en[key].trim(), key).not.toBe('');
    }
  });
});

// Files that legitimately hold Vietnamese text outside the dictionaries: the dashboard dictionary (driven by the data's
// language), and patterns that PARSE Vietnamese text the backend writes (not text shown to the user).
const ALLOWED = new Set([
  'lib/locales/vi.ts',
  'lib/uiText.ts',
  'components/ChatMessage.tsx', // DASHBOARD_INTENT_REGEX and the markers of a data summary answer
  'components/DataSummaryView.tsx', // regexes that read the numbers out of the summary text
  'components/dashboard/DynamicDashboard.tsx', // bilingual "legacy dashboard" notice, "Khác" bucket name
  'lib/fileTypes.ts', // "danh mục:" typed by the user in the chat box
  'lib/formatters.ts', // Vietnamese unit names found in data
  'app/api/analyze/route.ts', // comments
  'app/api/chat/title/route.ts', // comments
]);
const VIETNAMESE = /[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]/i;

function sources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (['node_modules', '.next', 'tests', 'test-results'].includes(name)) continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) sources(path, out);
    else if (/\.(ts|tsx)$/.test(name)) out.push(path);
  }
  return out;
}

describe('no Vietnamese text outside the dictionaries', () => {
  it('every user-facing string goes through t(lang, key)', () => {
    const root = join(__dirname, '..', '..');
    const offenders: string[] = [];
    for (const dir of ['app', 'components', 'lib']) {
      for (const file of sources(join(root, dir))) {
        const rel = relative(root, file).split('\\').join('/');
        if (ALLOWED.has(rel)) continue;
        readFileSync(file, 'utf8').split('\n').forEach((line, i) => {
          const trimmed = line.trim();
          const comment = trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*') || trimmed.startsWith('{/*');
          if (VIETNAMESE.test(line) && !comment) offenders.push(`${rel}:${i + 1}: ${trimmed.slice(0, 80)}`);
        });
      }
    }
    expect(offenders).toEqual([]);
  });
});
