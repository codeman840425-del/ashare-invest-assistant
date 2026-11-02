import type { IngestDataset } from '../api/adminTypes';

/** 契约 v0.2.9 #31 ③：6 个数据集的中文显示名（前端显示名，不是接口字段） */
export const INGEST_DATASET_NAME: Record<IngestDataset, string> = {
  quotes: '实时行情', minute_bars: '分钟线', daily_bars: '日线', financials: '财务数据', announcements: '公告', security_master: '证券主数据',
};
