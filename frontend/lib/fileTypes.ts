/** Upload types. Tabular files go to the data agent (same list as the backend reader); documents go to RAG. */

export const TABULAR_EXTENSIONS = ['.csv', '.tsv', '.xlsx', '.parquet', '.json'] as const;
/** Documents are added to the RAG knowledge base (what the backend's document loader can read). */
export const DOCUMENT_EXTENSIONS = ['.pdf', '.docx', '.pptx', '.txt', '.md'] as const;
export const ACCEPT_ATTRIBUTE = [...TABULAR_EXTENSIONS, ...DOCUMENT_EXTENSIONS].join(',');
/** Mirrors the backend's DATA_MAX_FILE_MB. */
export const TABULAR_MAX_MB = 25;
/** Mirrors the backend's KNOWLEDGE_MAX_FILE_MB. */
export const DOCUMENT_MAX_MB = 25;

const CATEGORY_HINT = /(?:category|danh\s*mục|loại)\s*[:=]\s*([\p{L}\d_-]+)/iu;

/** Splits "category: nda  what is the term?" into the category the user named (if any) and the rest of the text. */
export function splitCategoryHint(text: string): { category: string | null; rest: string } {
  const match = CATEGORY_HINT.exec(text);
  if (!match) return { category: null, rest: text.trim() };
  return { category: match[1], rest: text.replace(match[0], '').trim() };
}

const endsWithAny = (name: string, extensions: readonly string[]) => extensions.some((ext) => name.toLowerCase().endsWith(ext));

export const isTabularFile = (name: string) => endsWithAny(name, TABULAR_EXTENSIONS);
export const isDocumentFile = (name: string) => endsWithAny(name, DOCUMENT_EXTENSIONS);
