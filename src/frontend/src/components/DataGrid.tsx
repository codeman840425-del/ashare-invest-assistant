/**
 * 表格封装（plan §2.10）：业务代码只用这里的列定义，不直接依赖 AG Grid。
 * 仅使用 AG Grid Community（MIT）—— 禁止引入 ag-grid-enterprise 或任何企业功能（eslint no-restricted-imports 兜底）。
 */
import { useEffect, useMemo, useRef, type ReactNode } from 'react';
import { AgGridReact } from 'ag-grid-react';
import {
  AllCommunityModule, ModuleRegistry, colorSchemeDark, themeBalham,
  type ColDef, type GetRowIdParams, type GridApi, type ICellRendererParams, type RowClassParams,
} from 'ag-grid-community';

ModuleRegistry.registerModules([AllCommunityModule]);

const gridTheme = themeBalham.withPart(colorSchemeDark).withParams({
  backgroundColor: '#0f141c',
  foregroundColor: '#d7dee8',
  headerBackgroundColor: '#121925',
  headerTextColor: '#9aa4b0',
  borderColor: '#1f2835',
  rowHoverColor: '#16202e',
  selectedRowBackgroundColor: '#15233a',
  accentColor: '#3b82f6',
  fontSize: 12,
  headerFontSize: 11,
  rowHeight: 28,
  headerHeight: 26,
  spacing: 4,
  fontFamily: '-apple-system, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", "Segoe UI", sans-serif',
  wrapperBorderRadius: 0,
});

const LOCALE_ZH = {
  noRowsToShow: '暂无数据', loadingOoo: '加载中…', page: '页', of: '/', to: '至', next: '下一页', previous: '上一页',
  sortAscending: '升序', sortDescending: '降序', sortUnSort: '取消排序', columnMenu: '列菜单',
};

export interface DataColumn<T> {
  key: string;
  header: string;
  width?: number;
  flex?: number;
  align?: 'left' | 'right' | 'center';
  numeric?: boolean;
  sortable?: boolean;
  pinned?: 'left' | 'right';
  /** 排序/默认展示用的原始值 */
  value?: (row: T) => string | number | null;
  render?: (row: T) => ReactNode;
  tooltip?: (row: T) => string | undefined;
}

export interface DataGridProps<T> {
  rows: T[];
  columns: DataColumn<T>[];
  getRowId: (row: T) => string;
  selectedId?: string | null;
  onRowClick?: (row: T) => void;
  onRowDoubleClick?: (row: T) => void;
  rowClass?: (row: T) => string | undefined;
  loading?: boolean;
  emptyText?: string;
  testId?: string;
  rowHeight?: number;
}

export function DataGrid<T>({ rows, columns, getRowId, selectedId, onRowClick, onRowDoubleClick, rowClass, loading, emptyText, testId, rowHeight }: DataGridProps<T>) {
  const colDefs = useMemo<ColDef<T>[]>(
    () =>
      columns.map((c) => ({
        colId: c.key,
        headerName: c.header,
        width: c.width,
        flex: c.flex,
        pinned: c.pinned,
        sortable: c.sortable ?? !!c.value,
        resizable: true,
        suppressMovable: true,
        cellClass: [c.numeric ? 'num-cell' : '', c.align === 'right' || c.numeric ? 'ag-right-aligned-cell' : ''].filter(Boolean),
        headerClass: c.align === 'right' || c.numeric ? 'ag-right-aligned-header' : undefined,
        valueGetter: c.value ? (p) => (p.data ? c.value!(p.data) : null) : undefined,
        cellRenderer: c.render ? (p: ICellRendererParams<T>) => (p.data ? c.render!(p.data) : null) : undefined,
        tooltipValueGetter: c.tooltip ? (p) => (p.data ? c.tooltip!(p.data) : undefined) : undefined,
      })),
    [columns],
  );
  const apiRef = useRef<GridApi<T> | null>(null);
  // 选中行样式依赖 selectedId：变化时重绘行
  useEffect(() => {
    apiRef.current?.redrawRows();
  }, [selectedId]);
  const lt = useMemo(() => ({ ...LOCALE_ZH, noRowsToShow: emptyText ?? LOCALE_ZH.noRowsToShow }), [emptyText]);
  return (
    <div className="grid-wrap" data-testid={testId}>
      <AgGridReact<T>
        theme={gridTheme}
        onGridReady={(e) => {
          apiRef.current = e.api;
        }}
        rowData={rows}
        columnDefs={colDefs}
        getRowId={(p: GetRowIdParams<T>) => getRowId(p.data)}
        getRowClass={(p: RowClassParams<T>) => {
          if (!p.data) return undefined;
          const cls = [rowClass?.(p.data), selectedId && getRowId(p.data) === selectedId ? 'row-selected' : undefined].filter(Boolean);
          return cls.length ? cls.join(' ') : undefined;
        }}
        onRowClicked={(e) => e.data && onRowClick?.(e.data)}
        onRowDoubleClicked={(e) => e.data && onRowDoubleClick?.(e.data)}
        loading={loading}
        localeText={lt}
        suppressCellFocus
        animateRows={false}
        tooltipShowDelay={400}
        rowHeight={rowHeight}
      />
    </div>
  );
}
