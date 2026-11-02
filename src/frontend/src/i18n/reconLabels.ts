/** T-F25：证券主数据对账差异文案（契约 v0.2.9 内 T-A04 #33 ③④；plan 4.6.4） */
import type { SecurityReconciliationKind, SecurityReconciliationSource } from '../api/enums';
import type { SecurityReconField } from '../api/adminTypes';

export const RECON_KIND: Record<SecurityReconciliationKind, { text: string; hint: string }> = {
  vendor_stale_listed: { text: '已终止上市仍在麦蕊列表', hint: '麦蕊列表里有，交易所已列为终止上市' },
  vendor_unknown: { text: '交易所名单里没有（隔离）', hint: '麦蕊列表里有，交易所三类名单都没有；该代码已隔离，搜索不到' },
  quote_missing: { text: '证书代码集缺少', hint: '交易所在列，但该证书的麦蕊代码集里没有；该证书用户搜索时会看到“行情源缺少该证券”' },
  quote_conflict: { text: '实时行情多行冲突', hint: '同一代码在实时全量里有多行且数值不同；只记录、不告警，这里不显示数值' },
  field_mismatch: { text: '字段不一致', hint: '交叉核对时与交易所的值不同；以交易所值为准' },
};

export const RECON_SOURCE: Record<SecurityReconciliationSource, string> = {
  mairui_lists: '麦蕊代码列表',
  mairui_real_all: '麦蕊实时全量',
  cninfo: '巨潮资讯',
  akshare: 'AKShare',
};

export const RECON_FIELD: Record<SecurityReconField, string> = {
  name: '简称',
  list_date: '上市日期',
  delist_date: '终止上市日期',
  exchange: '交易所',
  board: '板块',
};

/** 服务端给了前端不认识的取值时原样显示，不丢行（与 /admin/ingest 告警处理一致） */
export const reconKindText = (k: string) => RECON_KIND[k as SecurityReconciliationKind]?.text ?? k;
export const reconKindHint = (k: string) => RECON_KIND[k as SecurityReconciliationKind]?.hint ?? null;
export const reconSourceText = (s: string) => RECON_SOURCE[s as SecurityReconciliationSource] ?? s;
export const reconFieldText = (f: string) => RECON_FIELD[f as SecurityReconField] ?? f;
