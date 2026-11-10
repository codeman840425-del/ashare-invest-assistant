/**
 * T-F34：today 页空态与缺口展示（契约 docs/contracts/today-view.md，docs/T-A139=1c10a10）。
 * 纯函数：状态判定、北京时间换算、日报 gaps 解析。页面只负责渲染。
 */
import type { DailyReport, Gap, TodayResponse } from '../../api/types';

/** 「日报约 HH:MM 生成」的时刻（用户尚未定 17:30 还是 18:30，只改这一处） */
export const REPORT_EXPECTED_AT = '18:30';
/** 收盘后开始显示「盘后数据准备中」的时刻 */
export const POST_CLOSE_AT = '15:00';
/** 日报逾时 = 「日报约 HH:MM 生成」时刻 + 15 分钟（编排者裁定 ⑧；默认 18:30 → 18:45） */
export const REPORT_OVERDUE_GRACE_MIN = 15;
/** 「数据缺口」区最多列出的证券数 */
export const GAP_SECURITY_LIMIT = 10;

const SH_TZ = 'Asia/Shanghai';
const hhmm = (s: string) => { const [h, m] = s.split(':').map(Number); return h * 60 + m; };
const fmtHhmm = (min: number) => `${String(Math.floor(min / 60) % 24).padStart(2, '0')}:${String(min % 60).padStart(2, '0')}`;
/** 由「日报约 HH:MM 生成」时刻推导逾时阈值（HH:MM） */
export const overdueAt = (expectedAt: string = REPORT_EXPECTED_AT) => fmtHhmm(hhmm(expectedAt) + REPORT_OVERDUE_GRACE_MIN);
/** 日报逾时阈值（默认由 REPORT_EXPECTED_AT 推导，即 18:45） */
export const REPORT_OVERDUE_AT = overdueAt();
/** S4 文案随「日报约 HH:MM 生成」时刻变化 */
export const s4Text = (expectedAt: string = REPORT_EXPECTED_AT) => `盘后数据准备中，日报约 ${expectedAt} 生成。`;

/** server_time 换算到北京时间的「当日分钟数」；只用 Intl 并显式指定 timeZone，与浏览器/机器时区无关。无法解析时返回 null */
export function shanghaiMinutes(iso: string): number | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: SH_TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(d);
  const h = Number(parts.find((p) => p.type === 'hour')?.value);
  const m = Number(parts.find((p) => p.type === 'minute')?.value);
  return Number.isFinite(h) && Number.isFinite(m) ? h * 60 + m : null;
}

export type GlobalState = 'S1' | 'S2' | 'S3' | 'S4' | 'S5' | 'S6' | 'S7' | 'S8' | 'S9';

export const STATE_TEXT: Record<Exclude<GlobalState, 'S9'>, string> = {
  S1: '还没有导入持仓，导入后才能生成你的日报。',
  S2: '当前没有持仓，日报只覆盖你的自选。',
  S3: '今天休市，没有新的日报。',
  S4: s4Text(),
  S5: '今日日报还没有生成，请稍后再看。',
  S6: '今日行情数据未就绪，本日报未做策略分析。',
  S7: '行情数据源尚未开通，本日报未做策略分析。',
  S8: '今日盘后分析没有完成记录。',
};
export const S4_SIGNALS_UPDATED = '候选信号已更新。';
export const A1_TEXT = '暂时算不出账户总览（缺持仓价格或现金）。';
export const R2_TEXT = '今天没有新的候选信号。';
export const UNKNOWN_GAP_TEXT = '部分数据暂不可用。';

const hasHolding = (t: TodayResponse) => t.focus.items.some((r) => r.holding !== null);
export const hasSuggestion = (t: TodayResponse) => t.focus.items.some((r) => r.suggestion !== null);

/** 不依赖日报的前置状态（S1–S5）；都不命中返回 null */
export function preReportState(t: TodayResponse, expectedAt: string = REPORT_EXPECTED_AT): GlobalState | null {
  if (!hasHolding(t)) return t.reconciliation.status === 'not_imported' ? 'S1' : 'S2';
  if (t.session === 'non_trading_day') return 'S3';
  const st = t.daily_report.status;
  if (st === 'ready') return null;
  const now = shanghaiMinutes(t.server_time);
  if (now === null) return null; // 时间无法判定：不猜，不显示时段状态
  // S5：交易日、已到逾时阈值、仍为 not_yet
  if (st === 'not_yet' && now >= hhmm(overdueAt(expectedAt))) return 'S5';
  // S4：交易日、收盘后、日报未就绪（契约 15:00–18:30；18:30 到逾时阈值之间以及逾时后仍 generating 也保守按 S4，见待裁定）
  if (now >= hhmm(POST_CLOSE_AT)) return 'S4';
  return null;
}

/** 只有 daily_report.status 为 ready 时才请求日报详情；S1（无持仓、未导入）与 S3（休市）不请求 */
export function reportDateToFetch(t: TodayResponse): string | undefined {
  if (t.daily_report.status !== 'ready') return undefined;
  const pre = preReportState(t);
  return pre === 'S1' || pre === 'S3' ? undefined : t.daily_report.date;
}

// ---------- 日报 gaps 解析（契约 §1 解析规则、§2.3） ----------
export interface PipelineKey { code: string; param: string }
export function parsePipelineKey(key: string): PipelineKey | null {
  if (!key.startsWith('pipeline.')) return null;
  const rest = key.slice('pipeline.'.length);
  const i = rest.indexOf(':');
  return i < 0 ? { code: rest, param: '' } : { code: rest.slice(0, i), param: rest.slice(i + 1) };
}

interface GapDef { text: string; security?: boolean; route?: string; state?: 'S6' | 'S7' | 'S8' }
/** §2.3 缺口 code 文案表（20 个已知 code；第 21 行「其他未知 code」见 UNKNOWN_GAP_TEXT） */
export const GAP_CODES: Record<string, GapDef> = {
  daily_bars_not_ready: { text: STATE_TEXT.S6, state: 'S6' },
  owned_market_cache_adapter_missing: { text: STATE_TEXT.S7, state: 'S7' },
  daily_bars_missing: { text: '今日缺少日 K 数据，未参与分析。', security: true },
  daily_bar_conflict: { text: '日 K 数据有冲突，已沿用首次记录。', security: true },
  daily_bars_after_asof: { text: '日 K 晚于分析截止时间到达，今日未采用。', security: true },
  daily_bars_not_final: { text: '日 K 尚未确认为收盘数据，今日未采用。', security: true },
  security_board_missing: { text: '缺少板块信息，未参与分析。', security: true },
  owned_snapshot_licence_unbound: { text: '数据授权未绑定，结果仅供参考。', security: true },
  owned_snapshot_hash_conflict: { text: '今日数据快照异常，已保留首次结果。' },
  calendar_not_covered: { text: '交易日历未覆盖今天，未做分析。' },
  owned_source_security_missing: { text: '未进入今日数据快照，未参与分析。', security: true },
  owned_source_or_card_missing: { text: '数据快照或策略卡不可用，未做分析。' },
  security_not_eligible: { text: '该证券不在分析范围内（仅支持上市股票）。', security: true },
  active_instances_missing: { text: '还没有启用中的策略实例。', route: '/strategy-instances' },
  version_unavailable: { text: '策略版本暂不可用。' },
  runtime_lifecycle_blocked: { text: '有策略实例当前状态不能运行。', route: '/strategy-instances' },
  runtime_source_gate: { text: '策略所需的部分数据尚未验证，未做分析。' },
  engine_policy_seed_missing: { text: '系统配置未就绪，未做分析。', security: true },
  evaluated_input_gaps: { text: '部分输入数据缺失，结果不完整。', security: true },
  analysis: { text: STATE_TEXT.S8, state: 'S8' },
};

/** 日报带来的全局状态（S6–S8），都不命中为 S9 */
export function reportState(r: Pick<DailyReport, 'gaps'>): GlobalState {
  const codes = new Set(r.gaps.map((g) => parsePipelineKey(g.key)?.code).filter((c): c is string => !!c));
  if (codes.has('daily_bars_not_ready')) return 'S6';
  if (codes.has('owned_market_cache_adapter_missing')) return 'S7';
  if (codes.has('analysis')) return 'S8';
  return 'S9';
}

export interface GapLine { text: string; route?: string }
export interface SecurityGapRow { code: string; name: string | null; lines: GapLine[] }
export interface ReportGapView { securities: SecurityGapRow[]; hiddenCount: number; general: GapLine[] }

/** 系统证券代码格式（与后端 trades.normalize_code 输出一致）：6 位数字 + .SH/.SZ/.BJ（契约 §7 ④） */
export const SEC_RE = /^\d{6}\.(?:SH|SZ|BJ)$/;
export const USER_INPUT_GAP_TEXT = '有信息待补录。';
const pushLine = (lines: GapLine[], l: GapLine) => { if (!lines.some((x) => x.text === l.text)) lines.push(l); };

/**
 * 把日报 gaps 整理成「数据缺口」区：按证券合并（每只一行，最多 10 只），其余为账户/策略级的通用行。
 * - 未知 pipeline code 一律显示兜底文案，不显示原始 code（参数像证券代码时归到该证券行）；
 * - 已在顶部状态条显示的 S6–S8 不在本区重复；
 * - account / account.pnl_day 由账户总览（A1/A2）表达；stocks.<证券>.<维度>.<键>、stocks.change_from_previous、market 等不在 today 页展示；
 * - §2.3 未列出、reason 为 user_input_missing 的非 pipeline 缺口显示「有信息待补录。」去 /portfolio/import（§7 ⑦）；
 * - 与 /today.data_gaps 同 key 的项只由 /today 那一行显示（§7 ⑦，如 cash）；
 * - 证券参数必须完全符合 SEC_RE，否则作通用行，不生成证券链接（§7 ④）。
 */
export function buildReportGaps(
  gaps: Gap[], shownState: GlobalState, nameOf: (code: string) => string | null, todayKeys: ReadonlySet<string> = new Set(),
): ReportGapView {
  const bySec = new Map<string, GapLine[]>();
  const general: GapLine[] = [];
  const toSec = (code: string, l: GapLine) => { const lines = bySec.get(code) ?? []; pushLine(lines, l); bySec.set(code, lines); };
  for (const g of gaps) {
    if (todayKeys.has(g.key)) continue;
    const p = parsePipelineKey(g.key);
    if (p) {
      const def = GAP_CODES[p.code];
      if (!def) {
        // 未知 code：参数首段形如证券代码时归到该证券行（显示代码和名称），否则为通用行；均只显示兜底文案
        const sec = p.param.split(':')[0];
        if (SEC_RE.test(sec)) toSec(sec, { text: UNKNOWN_GAP_TEXT }); else pushLine(general, { text: UNKNOWN_GAP_TEXT });
        continue;
      }
      if (def.state && def.state === shownState) continue;
      const sec = def.security ? p.param.split(':')[0] : '';
      if (SEC_RE.test(sec)) toSec(sec, { text: def.text, route: def.route });
      else pushLine(general, { text: def.text, route: def.route });
      continue;
    }
    if (g.key === 'cash') { pushLine(general, { text: '未录入现金。', route: '/portfolio/import' }); continue; }
    const price = g.key.match(/^account\.(.+)\.price$/);
    if (price && SEC_RE.test(price[1])) { toSec(price[1], { text: '缺现价，按成本估算。' }); continue; }
    const stock = g.key.match(/^stocks\.(.+)$/);
    if (stock && SEC_RE.test(stock[1])) { toSec(stock[1], { text: '该股无候选信号。' }); continue; }
    // §2.3 已列出但 today 页不展示的：account、account.pnl_day（由 A1/A2 表达）、stocks.* 其余键、market
    if (g.key === 'account' || g.key === 'account.pnl_day' || g.key === 'market' || g.key.startsWith('market.') || g.key.startsWith('stocks.')) continue;
    // 其余未列出的：只有 user_input_missing 显示（用户能自己处理，不藏）
    if (g.reason === 'user_input_missing') pushLine(general, { text: USER_INPUT_GAP_TEXT, route: '/portfolio/import' });
  }
  const all = [...bySec.entries()].map(([code, lines]) => ({ code, name: nameOf(code), lines }));
  return { securities: all.slice(0, GAP_SECURITY_LIMIT), hiddenCount: Math.max(0, all.length - GAP_SECURITY_LIMIT), general };
}
