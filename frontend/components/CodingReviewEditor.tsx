'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { DiffEditor, loader } from '@monaco-editor/react';
import { ArrowLeft, CheckCircle2, ExternalLink, Loader2, Undo2, XCircle } from 'lucide-react';
import {
  getFiles, getReview, githubDevUrl, publishTask, reviseTask,
  type CodingFile, type CodingReview,
} from '../lib/codingApi';
import { t, useLang, type MessageKey } from '../lib/i18n';

// Monaco is served from this origin (scripts/copy-monaco.mjs): the CSP allows no CDN.
loader.config({ paths: { vs: '/monaco/vs' } });

const LANGUAGES: Record<string, string> = {
  py: 'python', ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript', mjs: 'javascript', json: 'json', md: 'markdown',
  css: 'css', html: 'html', yml: 'yaml', yaml: 'yaml', sh: 'shell', sql: 'sql', toml: 'ini',
};
const languageOf = (path: string): string => LANGUAGES[path.split('.').pop()?.toLowerCase() ?? ''] ?? 'plaintext';

/** Why a file cannot be edited here, as a message key (null = editable). Pure so it is tested without Monaco. */
export function readOnlyReason(file: CodingFile, editable: boolean): MessageKey | null {
  if (file.binary) return 'coding.editor.binary';
  if (file.too_large) return 'coding.editor.tooLarge';
  if (file.protected) return 'coding.editor.protectedFile';
  if (file.status === 'deleted') return 'coding.file.deleted';
  if (!editable) return 'coding.editor.notEditable';
  return null;
}

/** The files whose text differs from what the agent produced: the only ones sent back for the checks to run again. */
export function dirtyEdits(files: CodingFile[], edits: Record<string, string>): Record<string, string> {
  const dirty: Record<string, string> = {};
  for (const file of files) {
    if (file.path in edits && edits[file.path] !== file.after) dirty[file.path] = edits[file.path];
  }
  return dirty;
}

const isDark = () => typeof document !== 'undefined' && document.documentElement.classList.contains('dark');

/** The review page of a coding task: every changed file as a side-by-side diff (agent's base on the left, the change on the right), the right
 * side editable like an IDE. "Save and re-run the checks" sends the edited files to the sandbox, which runs ruff/pytest again; the publish
 * button then offers what those checks say, not what the agent claimed. */
export function CodingReviewEditor({ jobId }: { jobId: string }) {
  const [lang] = useLang();
  const [review, setReview] = useState<CodingReview | null>(null);
  const [files, setFiles] = useState<CodingFile[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [current, setCurrent] = useState<string | null>(null);
  const [busy, setBusy] = useState<'save' | 'publish' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [published, setPublished] = useState<{ pr_url?: string; branch: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const [next, list] = await Promise.all([getReview(jobId), getFiles(jobId)]);
      setReview(next);
      setFiles(list.files);
      setTruncated(list.truncated);
      setCurrent((c) => (c && list.files.some((f) => f.path === c) ? c : list.files[0]?.path ?? null));
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [jobId]);

  useEffect(() => {
    void load();
  }, [load]);

  const file = files.find((f) => f.path === current) ?? null;
  const dirty = useMemo(() => dirtyEdits(files, edits), [files, edits]);
  const dirtyCount = Object.keys(dirty).length;
  const result = review?.result ?? null;
  const reason = file ? readOnlyReason(file, Boolean(review?.editable)) : null;
  const prUrl = published?.pr_url ?? result?.pr_url ?? null;
  const devUrl = prUrl ? githubDevUrl(prUrl) : null;

  const save = async () => {
    setBusy('save');
    setError(null);
    setNotice(null);
    try {
      const revised = await reviseTask(jobId, dirty);
      setEdits({});
      await load();
      setNotice(t(lang, 'coding.editor.rechecked', { count: revised.revisions }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const publish = async () => {
    setBusy('publish');
    setError(null);
    try {
      setPublished(await publishTask(jobId));
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex h-screen flex-col bg-background text-foreground" data-testid="coding-review">
      <header className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-2">
        <Link href="/" className="flex items-center gap-1.5 text-sm text-foreground-secondary hover:text-foreground">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" /> {t(lang, 'coding.editor.back')}
        </Link>
        <h1 className="text-sm font-semibold">{t(lang, 'coding.editor.title')}</h1>
        {result?.repo && <span className="font-mono text-xs text-foreground-muted">{result.repo.name}</span>}
        <div className="ml-auto flex flex-wrap items-center gap-3 text-xs">
          {(['pytest', 'ruff'] as const).map((name) => {
            const check = result?.checks[name];
            return (
              <span key={name} className="flex items-center gap-1 text-foreground-secondary">
                {check?.ok ? <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> : <XCircle className={`h-4 w-4 ${check ? 'text-accent-error' : 'text-foreground-muted'}`} aria-hidden="true" />}
                <span className="font-mono">{name}</span> {t(lang, check ? (check.ok ? 'coding.check.passed' : 'coding.check.failed') : 'coding.check.notRun')}
              </span>
            );
          })}
          {dirtyCount > 0 && <span role="status" className="text-foreground-muted">{t(lang, 'coding.editor.dirty', { count: dirtyCount })}</span>}
          <button type="button" className="btn-dash" disabled={dirtyCount === 0 || busy !== null || !review?.editable} onClick={() => void save()}>
            {busy === 'save' ? <><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {t(lang, 'coding.editor.saving')}</> : t(lang, 'coding.editor.save')}
          </button>
          {devUrl && (
            <a href={devUrl} target="_blank" rel="noopener noreferrer" className="btn-dash inline-flex items-center gap-1.5">
              <ExternalLink className="h-4 w-4" aria-hidden="true" /> {t(lang, 'coding.openGithubDev')}
            </a>
          )}
          {prUrl ? (
            <a href={prUrl} target="_blank" rel="noopener noreferrer" className="btn-primary inline-flex items-center gap-1.5">
              <ExternalLink className="h-4 w-4" aria-hidden="true" /> {t(lang, 'coding.openPr')}
            </a>
          ) : result?.ready_for_review && review?.can_publish && dirtyCount === 0 && !result.branch ? (
            <button type="button" className="btn-primary" disabled={busy !== null} onClick={() => void publish()}>
              {busy === 'publish' ? <><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {t(lang, 'coding.publishing')}</> : t(lang, review.target === 'local' ? 'coding.publishLocal' : 'coding.publish')}
            </button>
          ) : null}
        </div>
      </header>

      {(error || notice || truncated || published?.branch) && (
        <div className="space-y-1 border-b border-border px-4 py-2 text-sm">
          {error && <p role="alert" className="whitespace-pre-wrap text-accent-error">{error}</p>}
          {notice && <p role="status" className="text-foreground-secondary">{notice}</p>}
          {truncated && <p className="text-foreground-muted">{t(lang, 'coding.editor.truncated')}</p>}
          {published && !published.pr_url && <p role="status" className="text-foreground-secondary">{t(lang, 'coding.branchCreated', { branch: published.branch })}</p>}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <nav aria-label={t(lang, 'coding.editor.files', { count: files.length })} className="w-64 shrink-0 overflow-auto border-r border-border p-2 max-md:w-40">
          <h2 className="px-2 pb-1 text-xs font-semibold uppercase tracking-wide text-foreground-muted">{t(lang, 'coding.editor.files', { count: files.length })}</h2>
          {!review && !error && <p className="flex items-center gap-1.5 px-2 text-sm text-foreground-muted"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {t(lang, 'coding.editor.loading')}</p>}
          <ul>
            {files.map((f) => (
              <li key={f.path}>
                <button
                  type="button"
                  aria-current={f.path === current}
                  onClick={() => setCurrent(f.path)}
                  className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-surface-raised ${f.path === current ? 'bg-surface-raised font-semibold' : ''}`}
                >
                  <span className="min-w-0 flex-1 truncate font-mono" title={f.path}>{f.path}</span>
                  {f.path in dirty && <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full bg-accent-primary" />}
                  <span className="shrink-0 text-foreground-muted">{t(lang, `coding.file.${f.status}` as MessageKey)}</span>
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <main className="flex min-w-0 flex-1 flex-col">
          {file ? (
            <>
              <div className="flex flex-wrap items-center gap-3 border-b border-border px-3 py-1.5 text-xs text-foreground-secondary">
                <span className="font-mono">{file.path}</span>
                {reason && <span>{t(lang, 'coding.editor.readOnly', { why: t(lang, reason) })}</span>}
                {file.path in dirty && (
                  <button type="button" className="inline-flex items-center gap-1 text-foreground-muted hover:text-foreground" onClick={() => setEdits(({ [file.path]: _drop, ...rest }) => rest)}>
                    <Undo2 className="h-3.5 w-3.5" aria-hidden="true" /> {t(lang, 'coding.editor.revert')}
                  </button>
                )}
              </div>
              <div className="min-h-0 flex-1">
                <DiffEditor
                  key={file.path}
                  original={file.before}
                  modified={edits[file.path] ?? file.after}
                  language={languageOf(file.path)}
                  theme={isDark() ? 'vs-dark' : 'vs'}
                  options={{ readOnly: reason !== null, originalEditable: false, renderSideBySide: true, automaticLayout: true, minimap: { enabled: false }, scrollBeyondLastLine: false, fontSize: 13 }}
                  onMount={(editor) => {
                    const modified = editor.getModifiedEditor();
                    modified.onDidChangeModelContent(() => {
                      const value = modified.getValue();
                      setEdits((prev) => (prev[file.path] === value ? prev : { ...prev, [file.path]: value }));
                    });
                  }}
                />
              </div>
            </>
          ) : (
            review && <p className="p-4 text-sm text-foreground-muted">{t(lang, 'coding.editor.pickFile')}</p>
          )}
        </main>
      </div>
    </div>
  );
}
