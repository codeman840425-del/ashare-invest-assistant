"""各 probe 共用的小工具：调用并记录摘要（含首/末行），可选保存样例。"""
import common as c


def probe(res, name, path_tpl, sample=None, n=3, pro=False, method="GET", json_body=None, **params):
    r = c.call(name, path_tpl, pro=pro, method=method, json_body=json_body, **params)
    s = c.summarize(r)
    rows = c.rows(r.data)
    if rows:
        s["first_row"], s["last_row"] = rows[0], rows[-1]
    elif isinstance(r.data, dict):
        s["sample"] = r.data
    res.append(s)
    if sample:
        c.save_sample(sample, r, n)
    return r
