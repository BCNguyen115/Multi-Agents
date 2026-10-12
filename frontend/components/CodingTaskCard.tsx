'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { CheckCircle2, ExternalLink, GitPullRequest, Loader2, XCircle } from 'lucide-react';
import { getReview, githubDevUrl, isFinished, publishTask, type CodingFinding, type CodingReview } from '../lib/codingApi';
import { t, useLang, type MessageKey } from '../lib/i18n';

const POLL_MS = 4000;
const SEVERITY: Record<string, MessageKey> = { high: 'coding.severity.high', medium: 'coding.severity.medium', low: 'coding.severity.low' };

function FindingRow({ finding }: { finding: CodingFinding }) {
  const [lang] = useLang();
  const where = `${finding.file}${finding.line ? `:${finding.line}` : ''}`;
  return (
    <li className="text-sm text-foreground-secondary">
      <span className={finding.severity === 'high' ? 'font-semibold text-accent-error' : 'font-semibold text-foreground'}>{t(lang, SEVERITY[finding.severity] ?? 'coding.severity.low')}</span>{' '}
      <span className="font-mono text-xs">{where}</span> {finding.summary ?? finding.rule}
    </li>
  );
}

/** A coding task from the chat: follows it until it finishes, then shows what an approver needs (checks, risks, the diff) and the one button
 * that opens a draft pull request. The server decides who may press it and whether the work qualifies; this only shows the outcome. */
export function CodingTaskCard({ jobId }: { jobId: string }) {
  const [lang] = useLang();
  const [review, setReview] = useState<CodingReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showDiff, setShowDiff] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [prUrl, setPrUrl] = useState<string | null>(null);
  const [localBranch, setLocalBranch] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const next = await getReview(jobId);
      setReview(next);
      setError(null);
      return next;
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    }
  }, [jobId]);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      const next = await load();
      if (!stopped && !(next && isFinished(next.status))) timer = setTimeout(tick, POLL_MS);
    };
    void tick();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [load]);

  const publish = async () => {
    setPublishing(true);
    setPublishError(null);
    try {
      const published = await publishTask(jobId);
      if (published.pr_url) setPrUrl(published.pr_url);
      else setLocalBranch(published.branch);
      await load();
    } catch (e: unknown) {
      setPublishError(e instanceof Error ? e.message : String(e));
    } finally {
      setPublishing(false);
    }
  };

  const result = review?.result ?? null;
  const url = prUrl ?? result?.pr_url ?? null;
  const branch = localBranch ?? (!url ? result?.branch : null) ?? null; // a branch was created but there is no pull request: the local repository

  return (
    <section aria-label={t(lang, 'coding.title')} className="space-y-3 rounded-xl border border-border bg-surface-raised/40 p-4" data-testid="coding-task">
      <div className="flex items-center gap-2">
        <GitPullRequest className="h-4 w-4 text-foreground-secondary" aria-hidden="true" />
        <h3 className="text-sm font-semibold text-foreground">{t(lang, 'coding.title')}</h3>
        <span className="ml-auto flex items-center gap-1.5 text-xs text-foreground-muted">
          {(!review || !isFinished(review.status)) && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          {review ? t(lang, `coding.status.${review.status}` as MessageKey) : null}
        </span>
      </div>

      {error && <p role="alert" className="text-sm text-accent-error">{t(lang, 'coding.loadFailed', { error })}</p>}
      {review?.status === 'failed' && <p role="alert" className="text-sm text-accent-error">{review.error}</p>}

      {result && (
        <div className="space-y-3">
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-foreground-muted">{t(lang, 'coding.summary')}</h4>
            <p className="mt-1 whitespace-pre-wrap text-sm text-foreground">{result.summary}</p>
            <p className="mt-1 text-xs text-foreground-muted">{t(lang, 'coding.cost', { cost: result.cost_usd.toFixed(2), steps: result.steps })}</p>
          </div>

          {result.plan.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-foreground-muted">{t(lang, 'coding.plan')}</h4>
              <ul className="mt-1 space-y-0.5 text-sm text-foreground-secondary">
                {result.plan.map((item) => (
                  <li key={item.content} className={item.status === 'done' ? 'line-through' : ''}>{item.content}</li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-foreground-muted">{t(lang, 'coding.checks')}</h4>
            <ul className="mt-1 space-y-0.5 text-sm">
              {(['pytest', 'ruff'] as const).map((name) => {
                const check = result.checks[name];
                return (
                  <li key={name} className="flex items-center gap-1.5 text-foreground-secondary">
                    {check?.ok ? <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> : <XCircle className={`h-4 w-4 ${check ? 'text-accent-error' : 'text-foreground-muted'}`} aria-hidden="true" />}
                    <span className="font-mono text-xs">{name}</span> {t(lang, check ? (check.ok ? 'coding.check.passed' : 'coding.check.failed') : 'coding.check.notRun')}
                  </li>
                );
              })}
            </ul>
          </div>

          {(result.commands?.length ?? 0) > 0 && (
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-foreground-muted">{t(lang, 'coding.commands', { count: result.commands?.length ?? 0 })}</h4>
              <ul className="mt-1 max-h-48 space-y-0.5 overflow-auto rounded-lg border border-border bg-surface p-2" tabIndex={0}>
                {result.commands?.map((c, i) => (
                  <li key={`${i}-${c.command}`} className="font-mono text-xs text-foreground-secondary">
                    <span className="text-foreground-muted">$</span> {c.command}{' '}
                    <span className={c.blocked || c.timed_out || (c.exit_code ?? 0) !== 0 ? 'text-accent-error' : 'text-foreground-muted'}>
                      {c.blocked ? t(lang, 'coding.command.blocked') : c.timed_out ? t(lang, 'coding.command.timedOut') : `exit ${c.exit_code}`}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {result.files_changed.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-foreground-muted">{t(lang, 'coding.files')}</h4>
              <ul className="mt-1 text-sm text-foreground-secondary">
                {result.files_changed.map((file) => <li key={file} className="font-mono text-xs">{file}</li>)}
              </ul>
            </div>
          )}

          {result.risk_findings.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-foreground-muted">{t(lang, 'coding.risks')}</h4>
              <ul className="mt-1 space-y-1">{result.risk_findings.map((f, i) => <FindingRow key={`${f.rule}-${f.file}-${i}`} finding={f} />)}</ul>
            </div>
          )}

          {(result.review?.findings?.length ?? 0) > 0 && (
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-foreground-muted">{t(lang, 'coding.review')}</h4>
              <ul className="mt-1 space-y-1">{result.review.findings.map((f, i) => <FindingRow key={`${f.file}-${i}`} finding={f} />)}</ul>
            </div>
          )}

          {result.patch && (
            <div>
              <button type="button" className="btn-dash" aria-expanded={showDiff} onClick={() => setShowDiff((v) => !v)}>
                {t(lang, showDiff ? 'coding.diff.hide' : 'coding.diff.show')}
              </button>
              {showDiff && (
                <pre className="mt-2 max-h-96 overflow-auto rounded-lg border border-border bg-surface p-3 font-mono text-xs text-foreground-secondary" tabIndex={0}>{result.patch}</pre>
              )}
            </div>
          )}

          <div className="space-y-2 border-t border-border pt-3">
            {result.files_changed.length > 0 && (
              <Link href={`/coding/${encodeURIComponent(jobId)}`} className="btn-dash inline-flex items-center gap-1.5" data-testid="open-diff-editor">
                <ExternalLink className="h-4 w-4" aria-hidden="true" /> {t(lang, 'coding.editor.open')}
              </Link>
            )}
            {url && githubDevUrl(url) && (
              <a href={githubDevUrl(url) ?? '#'} target="_blank" rel="noopener noreferrer" className="btn-dash ml-2 inline-flex items-center gap-1.5">
                <ExternalLink className="h-4 w-4" aria-hidden="true" /> {t(lang, 'coding.openGithubDev')}
              </a>
            )}
            {url ? (
              <a href={url} target="_blank" rel="noopener noreferrer" className="btn-primary inline-flex items-center gap-1.5">
                <ExternalLink className="h-4 w-4" aria-hidden="true" /> {t(lang, 'coding.openPr')}
              </a>
            ) : branch ? (
              <p role="status" className="flex items-start gap-1.5 text-sm text-foreground-secondary">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /> {t(lang, 'coding.branchCreated', { branch })}
              </p>
            ) : result.ready_for_review ? (
              <>
                <p className="flex items-center gap-1.5 text-sm text-foreground-secondary"><CheckCircle2 className="h-4 w-4" aria-hidden="true" /> {t(lang, 'coding.ready')}</p>
                {review?.can_publish ? (
                  <button type="button" className="btn-primary" disabled={publishing} onClick={publish}>
                    {publishing ? <><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {t(lang, 'coding.publishing')}</> : t(lang, review.target === 'local' ? 'coding.publishLocal' : 'coding.publish')}
                  </button>
                ) : (
                  <p className="text-sm text-foreground-muted">{t(lang, 'coding.needApprover')}</p>
                )}
              </>
            ) : (
              <p className="text-sm text-foreground-secondary"><span className="font-semibold">{t(lang, 'coding.notReady')}.</span> {t(lang, 'coding.notReadyWhy')}</p>
            )}
            {publishError && <p role="alert" className="text-sm text-accent-error">{t(lang, 'coding.publishFailed', { error: publishError })}</p>}
          </div>
        </div>
      )}
    </section>
  );
}
