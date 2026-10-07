import * as duckdb from '@duckdb/duckdb-wasm';
import { CSVMetadata } from './types';

/** The DuckDB-WASM bundles, served by this app (public/duckdb, copied by scripts/copy-duckdb.mjs): no CDN, and absolute URLs
 *  because the worker is started from a blob: URL, where a relative path would not resolve. */
export function localBundles(origin: string): duckdb.DuckDBBundles {
  const at = (file: string) => `${origin}/duckdb/${file}`;
  return {
    mvp: { mainModule: at('duckdb-mvp.wasm'), mainWorker: at('duckdb-browser-mvp.worker.js') },
    eh: { mainModule: at('duckdb-eh.wasm'), mainWorker: at('duckdb-browser-eh.worker.js') },
  };
}

let dbInstance: duckdb.AsyncDuckDB | null = null;
let dbInitPromise: Promise<duckdb.AsyncDuckDB> | null = null;

export async function getDuckDB(): Promise<duckdb.AsyncDuckDB> {
  if (dbInstance) return dbInstance;
  if (dbInitPromise) return dbInitPromise;

  dbInitPromise = (async () => {
    const bundle = await duckdb.selectBundle(localBundles(window.location.origin));

    const worker_url = URL.createObjectURL(
      new Blob([`importScripts("${bundle.mainWorker!}");`], { type: 'text/javascript' })
    );

    const worker = new Worker(worker_url);
    const logger = new duckdb.ConsoleLogger();
    const db = new duckdb.AsyncDuckDB(logger, worker);
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    URL.revokeObjectURL(worker_url);
    dbInstance = db;
    return db;
  })();

  return dbInitPromise;
}

export async function processCSVWithDuckDB(file: File): Promise<{
  metadata: CSVMetadata;
  tableName: string;
}> {
  const db = await getDuckDB();
  const conn = await db.connect();

  const text = await file.text();
  // Unique even when the same file is loaded twice within one millisecond (select + send race)
  const tableName = `csv_data_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  await db.registerFileText(tableName, text);

  await conn.insertCSVFromPath(tableName, {
    name: tableName,
    schema: 'main',
    header: true,
    detect: true,
  });

  const schemaRes = await conn.query(`DESCRIBE ${tableName};`);
  const schemaRows = schemaRes.toArray().map((row) => row.toJSON());

  const columns: { name: string; type: string }[] = schemaRows.map((r) => ({
    name: String(r.column_name),
    type: String(r.column_type),
  }));

  const countRes = await conn.query(`SELECT COUNT(*) as total_rows FROM ${tableName};`);
  const totalRows = Number(countRes.toArray()[0].toJSON().total_rows);

  const sampleRes = await conn.query(`SELECT * FROM ${tableName} LIMIT 5;`);
  const sampleData = sampleRes.toArray().map((row) => row.toJSON());

  const isIdColName = (colName: string) => {
    const k = colName.toLowerCase();
    return (
      k === 'id' ||
      k.includes('id_') ||
      k.endsWith('_id') ||
      k.includes('code') ||
      k.includes('zip') ||
      k.includes('phone') ||
      k.includes('index') ||
      k.includes('ssn') ||
      k.endsWith('_num') ||
      k.endsWith('number')
    );
  };

  const numericCols: string[] = [];
  const categoricalCols: string[] = [];

  for (const col of columns) {
    const t = col.type.toUpperCase();
    const isNum = (t.includes('INT') || t.includes('FLOAT') || t.includes('DOUBLE') || t.includes('DECIMAL') || t.includes('BIGINT') || t.includes('REAL'));
    if (isNum && !isIdColName(col.name)) {
      numericCols.push(col.name);
    } else {
      categoricalCols.push(col.name);
    }
  }

  const summary: Record<string, { min?: number; max?: number; avg?: number; sum?: number }> = {};
  for (const col of numericCols.slice(0, 5)) {
    const statsRes = await conn.query(
      `SELECT MIN("${col}") as col_min, MAX("${col}") as col_max, AVG("${col}") as col_avg, SUM("${col}") as col_sum FROM ${tableName};`
    );
    const statRow = statsRes.toArray()[0]?.toJSON();
    if (statRow) {
      summary[col] = {
        min: Number(statRow.col_min ?? 0),
        max: Number(statRow.col_max ?? 0),
        avg: Number(statRow.col_avg ?? 0),
        sum: Number(statRow.col_sum ?? 0),
      };
    }
  }

  await conn.close();

  const metadata: CSVMetadata = {
    filename: file.name,
    totalRows,
    totalCols: columns.length,
    columns,
    categoricalCols,
    numericCols,
    sampleData,
    summary,
  };

  return { metadata, tableName };
}

export async function executeDuckDBSQL(tableName: string, sqlQuery: string): Promise<Record<string, any>[]> {
  const db = await getDuckDB();
  const conn = await db.connect();
  try {
    const res = await conn.query(sqlQuery);
    return res.toArray().map((r) => r.toJSON());
  } finally {
    await conn.close();
  }
}


