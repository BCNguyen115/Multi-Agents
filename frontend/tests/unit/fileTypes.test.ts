import { describe, expect, it } from 'vitest';
import { isDocumentFile, isTabularFile, splitCategoryHint } from '../../lib/fileTypes';

describe('file types', () => {
  it('sends only what the backend loader reads to the knowledge base', () => {
    expect(isDocumentFile('Contract.PDF')).toBe(true);
    expect(isDocumentFile('memo.docx')).toBe(true);
    expect(isDocumentFile('notes.txt')).toBe(true);
    expect(isDocumentFile('deck.pptx')).toBe(true);
    expect(isDocumentFile('memo.doc')).toBe(false);
    expect(isDocumentFile('notes.exe')).toBe(false);
    expect(isTabularFile('sales.csv')).toBe(true);
  });
});

describe('splitCategoryHint', () => {
  it('reads the category the user named and leaves the rest as the question', () => {
    expect(splitCategoryHint('category: nda điều khoản bảo mật kéo dài bao lâu?')).toEqual({
      category: 'nda',
      rest: 'điều khoản bảo mật kéo dài bao lâu?',
    });
    expect(splitCategoryHint('Danh mục = hop-dong')).toEqual({ category: 'hop-dong', rest: '' });
  });

  it('returns no category when none is named', () => {
    expect(splitCategoryHint('  thời hạn hợp đồng là gì?  ')).toEqual({ category: null, rest: 'thời hạn hợp đồng là gì?' });
  });
});
