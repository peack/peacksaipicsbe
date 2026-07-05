CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  size INTEGER,
  mtime REAL,
  source TEXT,
  status TEXT DEFAULT 'pending',
  last_scanned REAL,
  created_at REAL
);

CREATE TABLE IF NOT EXISTS generation_meta (
  item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  prompt TEXT,
  negative_prompt TEXT,
  model TEXT,
  sampler TEXT,
  steps INTEGER,
  cfg_scale REAL,
  seed TEXT,
  width INTEGER,
  height INTEGER,
  raw_json TEXT
);

CREATE TABLE IF NOT EXISTS item_tags (
  item_id INTEGER REFERENCES items(id) ON DELETE CASCADE,
  tag TEXT,
  tag_type TEXT,
  PRIMARY KEY (item_id, tag, tag_type)
);

CREATE VIRTUAL TABLE IF NOT EXISTS generation_meta_fts USING fts5(
  item_id UNINDEXED, prompt, negative_prompt
);

CREATE TRIGGER IF NOT EXISTS gen_meta_ai AFTER INSERT ON generation_meta BEGIN
  INSERT INTO generation_meta_fts(item_id, prompt, negative_prompt)
  VALUES (new.item_id, new.prompt, new.negative_prompt);
END;

CREATE TRIGGER IF NOT EXISTS gen_meta_ad AFTER DELETE ON generation_meta BEGIN
  DELETE FROM generation_meta_fts WHERE item_id = old.item_id;
END;

CREATE TRIGGER IF NOT EXISTS gen_meta_au AFTER UPDATE ON generation_meta BEGIN
  DELETE FROM generation_meta_fts WHERE item_id = old.item_id;
  INSERT INTO generation_meta_fts(item_id, prompt, negative_prompt)
  VALUES (new.item_id, new.prompt, new.negative_prompt);
END;