import { describe, expect, it } from 'vitest';
import { describeDetail, githubDevUrl, type CodingFile } from '../../lib/codingApi';
import { dirtyEdits, readOnlyReason } from '../../components/CodingReviewEditor';

const file = (over: Partial<CodingFile> = {}): CodingFile => ({ path: 'src/a.py', status: 'modified', before: 'a\n', after: 'b\n', protected: false, ...over });

describe('github.dev link', () => {
  it('is built from a github.com pull request and from nothing else', () => {
    expect(githubDevUrl('https://github.com/o/r/pull/7')).toBe('https://github.dev/o/r/pull/7');
    expect(githubDevUrl('https://evil.example/o/r/pull/7')).toBeNull();
    expect(githubDevUrl('not a url')).toBeNull();
  });
});

describe('which files a reviewer may edit', () => {
  it('refuses binary, oversized, protected and deleted files, and everything once the sandbox is gone', () => {
    expect(readOnlyReason(file(), true)).toBeNull();
    expect(readOnlyReason(file({ binary: true }), true)).toBe('coding.editor.binary');
    expect(readOnlyReason(file({ too_large: true }), true)).toBe('coding.editor.tooLarge');
    expect(readOnlyReason(file({ protected: true }), true)).toBe('coding.editor.protectedFile');
    expect(readOnlyReason(file({ status: 'deleted' }), true)).toBe('coding.file.deleted');
    expect(readOnlyReason(file(), false)).toBe('coding.editor.notEditable');
  });

  it("sends back only the files whose text really differs from the agent's", () => {
    const files = [file({ path: 'a.py' }), file({ path: 'b.py' })];
    expect(dirtyEdits(files, { 'a.py': 'b\n', 'b.py': 'changed\n' })).toEqual({ 'b.py': 'changed\n' });
    expect(dirtyEdits(files, {})).toEqual({});
  });
});

describe('server refusals', () => {
  it('read as one message, with the reason of every refused file', () => {
    expect(describeDetail('plain')).toBe('plain');
    expect(describeDetail({ message: 'Edit refused', errors: { 'x.py': 'protected' } })).toBe('Edit refused\nx.py: protected');
    expect(describeDetail(undefined)).toBe('');
  });
});
