-- Desktop clusters use locale C, whose ILIKE only folds ASCII case.
CREATE COLLATION search_unicode (provider = icu, locale = 'und', deterministic = true);
DROP INDEX goals_search;
CREATE INDEX goals_search ON goals USING GIN
    ((title || ' ' || body) COLLATE search_unicode gin_trgm_ops);
