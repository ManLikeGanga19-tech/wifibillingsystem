import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  AlertTriangle, ArrowDown, ArrowUp, ChevronLeft, ChevronRight, ChevronsUpDown, Loader2, Search,
} from 'lucide-react';
import { ApiError, type Paginated } from '../api/client';

/** One column of a DataTable. `sortKey` is the backend ordering field; omit it to make the
 *  column non-sortable. `render` draws the cell from the row. */
export interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
  sortKey?: string;
  className?: string;
}

const PAGE_SIZES = [25, 50, 100];

/**
 * Server-side paginated table. Owns page / page_size / search / ordering, builds the query, and
 * fetches through `fetcher` — the same `{count, next, previous, results}` every list endpoint
 * returns. Search is debounced; any change to search / sort / page-size / external `filters`
 * resets to page 1. One component so every table in the console behaves the same.
 */
export default function DataTable<T>({
  fetcher,
  columns,
  rowKey,
  filters,
  searchPlaceholder = 'Search…',
  searchable = true,
  emptyMessage = 'Nothing here yet.',
  initialOrdering = '',
  toolbar,
  refreshSignal,
  onLoaded,
}: {
  fetcher: (query: string) => Promise<Paginated<T>>;
  columns: Column<T>[];
  rowKey: (row: T) => string | number;
  filters?: Record<string, string | number | boolean | undefined>;
  searchPlaceholder?: string;
  searchable?: boolean;
  emptyMessage?: string;
  initialOrdering?: string;   // e.g. '-created_at'
  toolbar?: ReactNode;        // extra controls (filter chips, dropdowns) rendered by the parent
  refreshSignal?: number;     // bump to force a reload (e.g. after a create/delete)
  onLoaded?: (count: number) => void;  // total row count, for parent summary cards
}) {
  const [rows, setRows] = useState<T[] | null>(null);
  const [count, setCount] = useState(0);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [ordering, setOrdering] = useState(initialOrdering);

  // Debounce the search box so a keystroke isn't a request.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Any change to what we're viewing (except the page itself) snaps back to page 1.
  const filterKey = JSON.stringify(filters ?? {});
  useEffect(() => { setPage(1); }, [debouncedSearch, ordering, pageSize, filterKey]);

  const query = useMemo(() => {
    const p = new URLSearchParams();
    p.set('page', String(page));
    p.set('page_size', String(pageSize));
    if (debouncedSearch) p.set('search', debouncedSearch);
    if (ordering) p.set('ordering', ordering);
    for (const [k, v] of Object.entries(filters ?? {})) {
      if (v !== undefined && v !== '') p.set(k, String(v));
    }
    return `?${p.toString()}`;
  }, [page, pageSize, debouncedSearch, ordering, filterKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the latest fetcher without making it a fetch dependency (parents often pass an inline fn).
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const onLoadedRef = useRef(onLoaded);
  onLoadedRef.current = onLoaded;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetcherRef.current(query);
      setRows(r.results);
      setCount(r.count);
      onLoadedRef.current?.(r.count);
      setError('');
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return;
      setError('Could not load data — check the API connection.');
    } finally {
      setLoading(false);
    }
  }, [query]);

  useEffect(() => { load(); }, [load, refreshSignal]);

  const toggleSort = (key: string) => {
    setOrdering((cur) => (cur === key ? `-${key}` : cur === `-${key}` ? key : key));
  };

  const from = count === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, count);
  const lastPage = Math.max(1, Math.ceil(count / pageSize));

  return (
    <div className="space-y-2">
      {(searchable || toolbar) && (
        <div className="flex flex-wrap items-center gap-2">
          {searchable && (
            <div className="flex items-center gap-2 border border-[#141414]/25 bg-white px-2.5 py-1.5 focus-within:border-[#141414]">
              <Search className="h-3.5 w-3.5 text-[#141414]/50" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={searchPlaceholder}
                className="w-48 bg-transparent text-xs outline-none placeholder:text-[#141414]/40"
                aria-label={searchPlaceholder}
              />
            </div>
          )}
          {toolbar}
          {loading && rows !== null && (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-[#141414]/40" />
          )}
        </div>
      )}

      <div className="bg-white border border-[#141414] overflow-x-auto">
        {error && (
          <p className="p-6 text-center text-xs font-mono text-[#B22222] flex items-center justify-center gap-2">
            <AlertTriangle className="h-4 w-4" /> {error}
          </p>
        )}
        {!error && rows === null && (
          <div className="flex justify-center py-14">
            <Loader2 className="h-6 w-6 animate-spin text-[#141414]/40" />
          </div>
        )}
        {!error && rows !== null && rows.length === 0 && (
          <p className="p-8 text-center text-xs font-mono text-[#141414]/50">{emptyMessage}</p>
        )}
        {!error && rows !== null && rows.length > 0 && (
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-[#141414] font-mono text-[11px] uppercase text-[#141414]/60">
                {columns.map((c) => {
                  const active = c.sortKey && (ordering === c.sortKey || ordering === `-${c.sortKey}`);
                  const desc = ordering === `-${c.sortKey}`;
                  return (
                    <th key={c.header} className={`py-2.5 px-3 whitespace-nowrap ${c.className ?? ''}`}>
                      {c.sortKey ? (
                        <button
                          onClick={() => toggleSort(c.sortKey!)}
                          className={`flex items-center gap-1 uppercase hover:text-[#141414] ${active ? 'text-[#141414]' : ''}`}
                        >
                          {c.header}
                          {!active && <ChevronsUpDown className="h-3 w-3 opacity-40" />}
                          {active && (desc ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />)}
                        </button>
                      ) : (
                        c.header
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#141414]/10">
              {rows.map((row) => (
                <tr key={rowKey(row)} className="hover:bg-[#f4f4f2]">
                  {columns.map((c) => (
                    <td key={c.header} className={`py-2.5 px-3 text-xs ${c.className ?? ''}`}>
                      {c.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pager */}
      {!error && count > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] font-mono text-[#141414]/60">
          <span>
            {from}–{to} of {count}
          </span>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1">
              Rows
              <select
                value={pageSize}
                onChange={(e) => setPageSize(Number(e.target.value))}
                className="border border-[#141414]/25 bg-white px-1 py-0.5"
              >
                {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="border border-[#141414]/25 p-1 disabled:opacity-30 hover:border-[#141414]"
                aria-label="Previous page"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
              <span className="px-1">{page} / {lastPage}</span>
              <button
                onClick={() => setPage((p) => Math.min(lastPage, p + 1))}
                disabled={page >= lastPage}
                className="border border-[#141414]/25 p-1 disabled:opacity-30 hover:border-[#141414]"
                aria-label="Next page"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
