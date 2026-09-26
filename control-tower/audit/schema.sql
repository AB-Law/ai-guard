CREATE TABLE IF NOT EXISTS audit_log (
    entry_id TEXT PRIMARY KEY,
    process TEXT NOT NULL,
    step_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    scores_json TEXT,
    timestamp TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    trace_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_process ON audit_log(process);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_log(event_type);

-- Non-chained query index for injection incidents (points at audit_log.entry_id).
CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL,
    process_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_incidents_process ON incidents(process_id);
CREATE INDEX IF NOT EXISTS idx_incidents_entry ON incidents(entry_id);
