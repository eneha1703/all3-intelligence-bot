CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  layer TEXT NOT NULL,
  is_direct_source INTEGER NOT NULL,
  is_wrapper INTEGER NOT NULL,
  enabled INTEGER NOT NULL,
  base_url TEXT,
  config_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
  id TEXT PRIMARY KEY,
  pipeline TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  config_snapshot_json TEXT NOT NULL,
  summary_json TEXT
);

CREATE TABLE IF NOT EXISTS raw_items (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  external_id TEXT,
  url TEXT NOT NULL,
  title TEXT,
  snippet TEXT,
  author TEXT,
  published_ts TEXT,
  collected_ts TEXT NOT NULL,
  raw_payload_json TEXT NOT NULL,
  fetch_status TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES pipeline_runs(id),
  FOREIGN KEY(source_id) REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS normalized_items (
  id TEXT PRIMARY KEY,
  raw_item_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  domain TEXT NOT NULL,
  title TEXT NOT NULL,
  dek TEXT,
  text_preview TEXT,
  published_ts TEXT,
  collected_ts TEXT NOT NULL,
  language TEXT,
  layer TEXT NOT NULL,
  is_wrapper INTEGER NOT NULL,
  directness_rank INTEGER NOT NULL,
  metadata_json TEXT NOT NULL,
  FOREIGN KEY(raw_item_id) REFERENCES raw_items(id),
  FOREIGN KEY(source_id) REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS canonical_events (
  id TEXT PRIMARY KEY,
  representative_item_id TEXT,
  event_key TEXT NOT NULL,
  cluster_title TEXT NOT NULL,
  first_published_ts TEXT,
  last_published_ts TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_members (
  canonical_event_id TEXT NOT NULL,
  normalized_item_id TEXT NOT NULL,
  is_representative INTEGER NOT NULL,
  PRIMARY KEY(canonical_event_id, normalized_item_id),
  FOREIGN KEY(canonical_event_id) REFERENCES canonical_events(id),
  FOREIGN KEY(normalized_item_id) REFERENCES normalized_items(id)
);

CREATE TABLE IF NOT EXISTS competitor_matches (
  normalized_item_id TEXT NOT NULL,
  competitor_name TEXT NOT NULL,
  alias_matched TEXT NOT NULL,
  match_field TEXT NOT NULL,
  PRIMARY KEY(normalized_item_id, competitor_name, alias_matched),
  FOREIGN KEY(normalized_item_id) REFERENCES normalized_items(id)
);

CREATE TABLE IF NOT EXISTS radar_decisions (
  normalized_item_id TEXT PRIMARY KEY,
  canonical_event_id TEXT,
  freshness_status TEXT NOT NULL,
  relevance_status TEXT NOT NULL,
  send_status TEXT NOT NULL,
  skip_reason TEXT,
  score INTEGER NOT NULL,
  signals_json TEXT NOT NULL,
  summary_text TEXT,
  used_gemini INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(normalized_item_id) REFERENCES normalized_items(id),
  FOREIGN KEY(canonical_event_id) REFERENCES canonical_events(id)
);

CREATE TABLE IF NOT EXISTS telegram_deliveries (
  id TEXT PRIMARY KEY,
  bot_kind TEXT NOT NULL,
  run_id TEXT NOT NULL,
  normalized_item_id TEXT,
  canonical_event_id TEXT,
  chat_id TEXT NOT NULL,
  telegram_message_id TEXT,
  status TEXT NOT NULL,
  payload_text TEXT,
  error_text TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES pipeline_runs(id)
);

CREATE TABLE IF NOT EXISTS editorial_signals (
  id TEXT PRIMARY KEY,
  signal_type TEXT NOT NULL,
  signal_state TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  normalized_item_id TEXT NOT NULL,
  canonical_event_id TEXT,
  chat_id TEXT NOT NULL DEFAULT '',
  telegram_message_id TEXT NOT NULL DEFAULT '',
  user_id TEXT NOT NULL DEFAULT '',
  username TEXT NOT NULL DEFAULT '',
  raw_value TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(normalized_item_id) REFERENCES normalized_items(id),
  FOREIGN KEY(canonical_event_id) REFERENCES canonical_events(id),
  UNIQUE(signal_type, source_kind, normalized_item_id, chat_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_editorial_signals_active_type
  ON editorial_signals(signal_type, signal_state, updated_at);

CREATE INDEX IF NOT EXISTS idx_editorial_signals_canonical_event
  ON editorial_signals(canonical_event_id);

CREATE TABLE IF NOT EXISTS integration_cursors (
  consumer_key TEXT PRIMARY KEY,
  cursor_value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weekly_digest_runs (
  id TEXT PRIMARY KEY,
  pipeline_run_id TEXT NOT NULL,
  week_key TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  shortlist_json TEXT,
  final_digest_markdown TEXT,
  final_digest_html TEXT,
  FOREIGN KEY(pipeline_run_id) REFERENCES pipeline_runs(id)
);

CREATE TABLE IF NOT EXISTS weekly_digest_candidates (
  digest_run_id TEXT NOT NULL,
  canonical_event_id TEXT NOT NULL,
  score INTEGER NOT NULL,
  rationale_json TEXT NOT NULL,
  PRIMARY KEY(digest_run_id, canonical_event_id),
  FOREIGN KEY(digest_run_id) REFERENCES weekly_digest_runs(id),
  FOREIGN KEY(canonical_event_id) REFERENCES canonical_events(id)
);
