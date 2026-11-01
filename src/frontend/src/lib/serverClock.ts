/**
 * 服务端时钟校正（契约 v0.2.8 #11，注册蜜罐 form_started_at）：
 * 用 GET /meta/registration 响应头 Date 与本地收到响应时的时钟算差值。
 * Date 只到秒且早于收到时刻，所以“Date − 本地收到时刻”是真实差值的下界：
 * 校正后的 form_started_at 只会偏早、不会偏晚，正常用户不会因为时钟误差被判为“填写太快”。
 */
let offsetMs = 0;

/** 由响应头 Date 和本地收到时刻求差值；没有或解析失败时返回 null（不改动已有差值） */
export function clockOffsetFromDate(dateHeader: string | null, receivedAtMs: number): number | null {
  const t = dateHeader ? Date.parse(dateHeader) : Number.NaN;
  return Number.isFinite(t) ? t - receivedAtMs : null;
}

export function noteServerDate(res: Response, receivedAtMs = Date.now()) {
  const o = clockOffsetFromDate(res.headers.get('Date'), receivedAtMs);
  if (o !== null) offsetMs = o;
}

/** 按服务端时钟校正后的当前毫秒时间（Unix epoch ms，整数） */
export const serverNowMs = () => Math.floor(Date.now() + offsetMs);

/** 测试用 */
export const resetServerClock = () => {
  offsetMs = 0;
};
