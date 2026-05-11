-- observability-control-plane schema

CREATE TABLE IF NOT EXISTS events (
    id         BIGSERIAL PRIMARY KEY,
    payload    JSONB        NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);

-- Seed some data
INSERT INTO events (payload, created_at)
SELECT
    jsonb_build_object('source', 'seed', 'index', i),
    NOW() - (i * interval '1 minute')
FROM generate_series(1, 50) AS i;

-- Connection pool monitoring view
CREATE OR REPLACE VIEW pg_pool_stats AS
SELECT
    count(*) FILTER (WHERE state = 'active')  AS active_connections,
    count(*) FILTER (WHERE state = 'idle')    AS idle_connections,
    count(*)                                   AS total_connections,
    max(now() - query_start) FILTER (WHERE state = 'active') AS longest_query
FROM pg_stat_activity
WHERE datname = current_database();
