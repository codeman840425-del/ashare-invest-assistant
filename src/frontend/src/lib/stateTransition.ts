/**
 * 409 INVALID_STATE_TRANSITION 按 details.from 区分文案（T-A10 P18；契约 §4 details = {from, to, allowed}，v0.2.9 #15 写明“已写明、不改”）。
 * 重新生成草案时原信号已失效 → 提示“信号已失效”（T-A10 P14，§7.7）。
 */
import { ApiError } from '../api/client';
import type { CandidateSignalState, PlanDraftStatus } from '../api/enums';
import { errorText } from '../api/errorPolicy';
import { PLAN_DRAFT_STATUS, SIGNAL_STATE } from '../i18n/labels';

const GONE: readonly CandidateSignalState[] = ['expired', 'invalidated', 'superseded'];

/** kind：出错对象是候选信号还是计划草案；regen：是否为“重新生成草案” */
export function transitionText(e: unknown, kind: 'signal' | 'draft', opts: { regen?: boolean } = {}): string | null {
  if (!(e instanceof ApiError) || e.code !== 'INVALID_STATE_TRANSITION') return null;
  const from = e.details?.from;
  if (typeof from !== 'string') return null;
  // 评审 b23401a N1：只认自有键，原型链上的键（如 "toString"）回落到通用文案
  if (kind === 'signal' && Object.hasOwn(SIGNAL_STATE, from)) {
    const st = from as CandidateSignalState;
    if (st === 'confirmed') return '该信号已被确认为计划';
    if (GONE.includes(st)) return opts.regen ? `信号已失效（${SIGNAL_STATE[st].text}），不能重新生成草案` : `信号已失效（${SIGNAL_STATE[st].text}）`;
    if (st === 'dismissed') return '该信号已忽略';
    return `该信号当前为“${SIGNAL_STATE[st].text}”，不能进行此操作`;
  }
  if (kind === 'draft' && Object.hasOwn(PLAN_DRAFT_STATUS, from)) {
    const st = from as PlanDraftStatus;
    if (st === 'confirmed') return '该草案已确认为计划';
    if (st === 'discarded') return '该草案已放弃';
    return `该草案当前为“${PLAN_DRAFT_STATUS[st].text}”，不能进行此操作`;
  }
  return null;
}

/** 先按状态跃迁给具体文案，否则回落到通用错误文案 */
export const stateErrorText = (e: unknown, kind: 'signal' | 'draft', opts: { regen?: boolean } = {}) => transitionText(e, kind, opts) ?? errorText(e);
