CREATE TABLE IF NOT EXISTS editorial_memory_examples (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  feedback_text TEXT NOT NULL,
  source TEXT,
  url TEXT,
  week_key TEXT,
  pipeline_stage TEXT,
  decision_tags_json TEXT NOT NULL,
  linked_rule_ids_json TEXT NOT NULL,
  resolution_status TEXT NOT NULL,
  source_fingerprint TEXT UNIQUE,
  metadata_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_editorial_memory_examples_kind
  ON editorial_memory_examples(kind, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_editorial_memory_examples_resolution
  ON editorial_memory_examples(resolution_status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_editorial_memory_examples_week
  ON editorial_memory_examples(week_key, created_at DESC);

