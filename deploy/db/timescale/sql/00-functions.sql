-- 会话级临时辅助函数（pg_temp，连接结束即消失，不在业务库留下任何对象）。
-- 由 db-apply-timescale.sh 在每次连接开头加载。

-- 把 "a/b" 解析为表中第一个存在的列；都不存在返回 NULL。
CREATE OR REPLACE FUNCTION pg_temp.aia_pick_col(p_rel regclass, p_alts text)
RETURNS text LANGUAGE sql STABLE AS $f$
  SELECT a.attname::text
  FROM unnest(string_to_array(p_alts, '/')) WITH ORDINALITY AS c(name, ord)
  JOIN pg_attribute a ON a.attrelid = p_rel AND a.attname = btrim(c.name) AND a.attnum > 0 AND NOT a.attisdropped
  ORDER BY c.ord LIMIT 1
$f$;

-- 解析逗号分隔的列清单（每项形如 "a/b [ASC|DESC] [NULLS ...]"）；任一项无对应列时返回 NULL。
CREATE OR REPLACE FUNCTION pg_temp.aia_resolve_list(p_rel regclass, p_spec text)
RETURNS text LANGUAGE plpgsql STABLE AS $f$
DECLARE
  item text; parts text[]; col text; out text[] := '{}';
BEGIN
  IF p_spec IS NULL OR btrim(p_spec) IN ('', '-') THEN RETURN ''; END IF;
  FOREACH item IN ARRAY string_to_array(p_spec, ',') LOOP
    parts := regexp_split_to_array(btrim(item), '\s+');
    col := pg_temp.aia_pick_col(p_rel, parts[1]);
    IF col IS NULL THEN RETURN NULL; END IF;
    out := out || btrim(quote_ident(col) || ' ' || array_to_string(parts[2:], ' '));
  END LOOP;
  RETURN array_to_string(out, ', ');
END $f$;

-- 规范化后比较（去空白、去引号、小写，ASC 视为默认）。
CREATE OR REPLACE FUNCTION pg_temp.aia_norm(p text)
RETURNS text LANGUAGE sql IMMUTABLE AS $f$
  SELECT regexp_replace(regexp_replace(lower(coalesce(p, '')), '\s+asc\b', '', 'g'), '[\s"]', '', 'g')
$f$;
