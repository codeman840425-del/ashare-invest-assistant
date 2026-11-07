/** evidence 里的 id 先校验是 uuid 再拼链接（review-787e453 m2），不是就只显示文本 */
export const isUuid = (v: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
