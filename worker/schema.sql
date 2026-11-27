-- Cloudflare D1 schema (run once):  npx wrangler d1 execute videobot --remote --file=schema.sql
CREATE TABLE IF NOT EXISTS users (
  id           INTEGER PRIMARY KEY,          -- Telegram user id
  name         TEXT    DEFAULT '',
  role         TEXT    DEFAULT 'member',     -- 'admin' | 'member'
  status       TEXT    DEFAULT 'pending',    -- 'pending' | 'approved' | 'blocked'
  settings     TEXT    DEFAULT '{}',         -- JSON: template, depth, gender, outputs[], captions, frame, video_type, extras[]
  state        TEXT    DEFAULT '',           -- what the bot is waiting for / which menu is open
  files        TEXT    DEFAULT '[]',         -- photos sent but not used yet (Telegram file_ids)
  files_at     INTEGER DEFAULT 0,
  day          TEXT    DEFAULT '',           -- UTC day of the counter below
  used         INTEGER DEFAULT 0,            -- videos started today
  lim          INTEGER DEFAULT 3,            -- daily limit for this member (admins are unlimited)
  active_until INTEGER DEFAULT 0,            -- a job is running until this unix time (cleared by /done)
  created      INTEGER DEFAULT 0
);
