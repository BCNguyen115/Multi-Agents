import { describe, expect, it } from 'vitest';
import { detectLang, t } from '../../lib/i18n';

describe('t', () => {
  it('fills placeholders and keeps unknown ones visible', () => {
    expect(t('en', 'login.failed', { status: 401 })).toBe('Sign-in failed (HTTP 401).');
    expect(t('vi', 'upload.saved', { chunks: 3, category: 'nda' })).toBe('Đã lưu 3 đoạn vào danh mục nda.');
    expect(t('en', 'upload.failed')).toBe('Could not update the knowledge base: {error}');
  });

  it('has the same wording slots in both languages', () => {
    const slots = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort().join();
    for (const key of ['login.failed', 'upload.processing', 'upload.failed', 'upload.saved'] as const) {
      expect(slots(t('vi', key))).toBe(slots(t('en', key)));
    }
  });
});

describe('detectLang', () => {
  it('prefers the saved choice, then the browser, and defaults to Vietnamese', () => {
    expect(detectLang('en', 'vi-VN')).toBe('en');
    expect(detectLang('vi', 'en-US')).toBe('vi');
    expect(detectLang(null, 'en-GB')).toBe('en');
    expect(detectLang(null, 'vi-VN')).toBe('vi');
    expect(detectLang(null, 'fr-FR')).toBe('vi');
    expect(detectLang('klingon', undefined)).toBe('vi');
  });
});
