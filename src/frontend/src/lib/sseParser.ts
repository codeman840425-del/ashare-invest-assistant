/**
 * text/event-stream 增量解析（契约 §8 GET /stream；按 WHATWG HTML “Server-sent events” 解析规则）。
 * 输入任意切分的文本块，输出完整事件：
 * - 行结束符 CRLF / LF / CR 都认（块边界上的 CR 留到下一块再判断）；
 * - 以 “:” 开头的是注释行（服务端保活用），忽略；
 * - 字段 `event` / `data`（多行拼接，以 \n 连接）/ `id`（含 NUL 时忽略）/ `retry`（纯数字才生效）；
 * - 空行分发事件；data 为空的事件不分发，但 `id` 照样更新 lastEventId。
 */
export interface SseMessage {
  /** 事件 id（契约：单调递增字符串）；本条未带 id 时沿用上一次的 lastEventId */
  id: string | null;
  /** 事件名；未带 event 字段时为 "message" */
  event: string;
  data: string;
}

export class SseParser {
  private buf = '';
  private data: string[] = [];
  private event = '';
  private pendingCR = false;
  lastEventId: string | null = null;
  /** 服务端通过 `retry:` 建议的重连间隔（毫秒） */
  retry: number | null = null;

  constructor(private readonly onMessage: (m: SseMessage) => void) {}

  push(chunk: string) {
    let text = chunk;
    // 上一块以 CR 结尾：若本块以 LF 开头，两者合成一个 CRLF
    if (this.pendingCR) {
      this.pendingCR = false;
      if (text.startsWith('\n')) text = text.slice(1);
    }
    this.buf += text;
    for (;;) {
      const m = /\r\n|\r|\n/.exec(this.buf);
      if (!m) break;
      // 块末尾的孤立 CR 可能是 CRLF 的前半，先按行结束处理并记下，下一块开头的 LF 丢弃
      if (m[0] === '\r' && m.index === this.buf.length - 1) this.pendingCR = true;
      const line = this.buf.slice(0, m.index);
      this.buf = this.buf.slice(m.index + m[0].length);
      this.line(line);
    }
  }

  /** 连接断开时丢弃未完成的事件（规范：流结束时不分发半截事件） */
  reset() {
    this.buf = '';
    this.data = [];
    this.event = '';
    this.pendingCR = false;
  }

  private line(line: string) {
    if (line === '') {
      this.dispatch();
      return;
    }
    if (line.startsWith(':')) return;
    const i = line.indexOf(':');
    const field = i < 0 ? line : line.slice(0, i);
    let value = i < 0 ? '' : line.slice(i + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    switch (field) {
      case 'event':
        this.event = value;
        break;
      case 'data':
        this.data.push(value);
        break;
      case 'id':
        if (!value.includes('\0')) this.lastEventId = value;
        break;
      case 'retry':
        if (/^\d+$/.test(value)) this.retry = Number(value);
        break;
      default:
        break;
    }
  }

  private dispatch() {
    const data = this.data;
    const event = this.event || 'message';
    this.data = [];
    this.event = '';
    if (!data.length) return;
    this.onMessage({ id: this.lastEventId, event, data: data.join('\n') });
  }
}
