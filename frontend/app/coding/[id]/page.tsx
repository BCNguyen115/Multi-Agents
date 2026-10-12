'use client';

import { useParams } from 'next/navigation';
import { CodingReviewEditor } from '../../../components/CodingReviewEditor';

/** `/coding/<task id>`: the diff editor for one coding task. The server decides who may open it (the owner, or an approver of the tenant). */
export default function CodingReviewPage() {
  const { id } = useParams<{ id: string }>();
  return <CodingReviewEditor jobId={id} />;
}
