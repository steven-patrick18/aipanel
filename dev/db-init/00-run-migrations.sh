#!/bin/bash
# Apply aipanel SQL migrations in order on first Postgres init.
#
# /docker-entrypoint-initdb.d/migrations/ is mounted from
# installer/migrations/ in the docker-compose. We just iterate the *.sql
# files (skipping the .down.sql rollbacks) in lexical order — the file
# names already encode dependency order (001_, 002_, 003_).
set -euo pipefail

shopt -s nullglob
for f in /docker-entrypoint-initdb.d/migrations/*.sql; do
    case "$f" in
        *.down.sql) continue ;;
    esac
    echo "[aipanel-dev] applying $(basename "$f")"
    psql -v ON_ERROR_STOP=1 \
         --username "$POSTGRES_USER" \
         --dbname "$POSTGRES_DB" \
         -f "$f"
done

# Bookkeeping table the bash migration runner usually populates — create
# it here so any future `aipanelctl migrate` against this dev DB sees the
# baselines as already applied.
psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text PRIMARY KEY,
    name       text NOT NULL,
    checksum   text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO schema_migrations (version, name, checksum)
VALUES
    ('001', 'initial',   'dev-bootstrap'),
    ('002', 'campaigns', 'dev-bootstrap'),
    ('003', 'pgvector',  'dev-bootstrap')
ON CONFLICT (version) DO NOTHING;
SQL

echo "[aipanel-dev] migrations applied"
