-- Ultra Fitness CRM：Cloudflare D1（SQLite）版資料表，等於 alembic 全部 migration（到 e2a7c4d91f30）套用後的結構。
-- 欄位、限制、索引都對應原本的 PostgreSQL 版；型別對應：
--   DATE → TEXT 'YYYY-MM-DD'、TIME → TEXT 'HH:MM:SS'、
--   DATETIME → TEXT 'YYYY-MM-DDTHH:MM:SS.ffffffZ'（一律 UTC、固定六位小數，字串比較＝時間比較）、
--   BOOLEAN → INTEGER 0/1、NUMERIC(10,2) → REAL（金額計算在程式裡用「分」算）、JSON → TEXT。
-- 之後要改結構：新增下一個編號的 .sql，只加不改（wrangler d1 migrations apply）。

CREATE TABLE members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  member_no TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  photo_url TEXT,
  line_user_id TEXT UNIQUE,
  role TEXT CHECK (role IN ('student', 'coach')),
  membership_active_until TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  membership_start_date TEXT,
  import_batch TEXT
);

CREATE TABLE venue_rental_coaches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  phone TEXT,
  line_user_id TEXT UNIQUE,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  import_batch TEXT
);

CREATE TABLE admin_users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('super_admin', 'manager', 'front_desk', 'coach')),
  is_active INTEGER NOT NULL DEFAULT 1,
  linked_member_id INTEGER REFERENCES members (id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);

CREATE TABLE binding_codes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL,
  member_id INTEGER REFERENCES members (id),
  venue_coach_id INTEGER REFERENCES venue_rental_coaches (id),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'used', 'expired', 'revoked')),
  expires_at TEXT NOT NULL,
  used_at TEXT,
  created_by_admin_id INTEGER REFERENCES admin_users (id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  CHECK ((member_id IS NOT NULL) != (venue_coach_id IS NOT NULL))
);

CREATE TABLE contracts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_no TEXT,
  coach_id INTEGER REFERENCES members (id),
  purchase_date TEXT NOT NULL,
  unit_price REAL NOT NULL,
  total_sessions INTEGER NOT NULL,
  used_sessions INTEGER NOT NULL DEFAULT 0,
  expiry_date TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'refunded', 'free')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  course_type TEXT NOT NULL DEFAULT 'strength' CHECK (course_type IN ('strength', 'pilates')),
  venue_coach_id INTEGER REFERENCES venue_rental_coaches (id),
  note TEXT,
  import_batch TEXT,
  CHECK ((coach_id IS NOT NULL AND venue_coach_id IS NULL) OR (coach_id IS NULL AND venue_coach_id IS NOT NULL))
);

CREATE TABLE contract_members (
  contract_id INTEGER NOT NULL REFERENCES contracts (id),
  member_id INTEGER NOT NULL REFERENCES members (id),
  PRIMARY KEY (contract_id, member_id)
);

CREATE TABLE contract_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id INTEGER NOT NULL REFERENCES contracts (id),
  session_no INTEGER NOT NULL,
  session_date TEXT,
  raw_value TEXT,
  import_batch TEXT,
  created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
CREATE INDEX ix_contract_sessions_contract_id ON contract_sessions (contract_id);
CREATE INDEX ix_contract_sessions_session_date ON contract_sessions (session_date);

CREATE TABLE class_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id INTEGER NOT NULL REFERENCES contracts (id),
  actual_teaching_coach_id INTEGER NOT NULL REFERENCES members (id),
  class_date TEXT NOT NULL,
  content_summary TEXT NOT NULL,
  logged_by_id INTEGER NOT NULL REFERENCES members (id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);

CREATE TABLE coach_unavailabilities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  coach_id INTEGER NOT NULL REFERENCES members (id),
  target_month TEXT NOT NULL,
  unavailable_date TEXT NOT NULL,
  shift TEXT NOT NULL CHECK (shift IN ('morning', 'afternoon', 'evening')),
  note TEXT,
  submitted_at TEXT NOT NULL
);

CREATE TABLE schedules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_date TEXT NOT NULL,
  shift TEXT NOT NULL CHECK (shift IN ('morning', 'afternoon', 'evening')),
  coach_id INTEGER REFERENCES members (id),
  admin_user_id INTEGER REFERENCES admin_users (id),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  CHECK ((coach_id IS NOT NULL) != (admin_user_id IS NOT NULL))
);

CREATE TABLE notification_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id INTEGER NOT NULL REFERENCES members (id),
  notif_type TEXT NOT NULL,
  contract_id INTEGER REFERENCES contracts (id),
  sent_at TEXT NOT NULL
);
CREATE UNIQUE INDEX ux_notification_logs_dedup ON notification_logs (member_id, notif_type, contract_id);

CREATE TABLE item_catalog_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_category TEXT NOT NULL CHECK (item_category IN ('service', 'venue_rental', 'membership', 'beverage', 'coaching', 'custom')),
  item_name TEXT NOT NULL,
  default_price REAL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);

CREATE TABLE revenue_details (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_date TEXT NOT NULL,
  item_category TEXT NOT NULL CHECK (item_category IN ('service', 'venue_rental', 'membership', 'beverage', 'coaching', 'custom')),
  item_name TEXT NOT NULL,
  coach_id INTEGER REFERENCES members (id),
  content TEXT,
  payment_method TEXT NOT NULL,
  amount REAL NOT NULL,
  contract_id INTEGER REFERENCES contracts (id),
  entered_by_id INTEGER NOT NULL REFERENCES admin_users (id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  remittance_last5 TEXT,
  import_batch TEXT,
  customer_name TEXT,
  coach_name TEXT
);
CREATE INDEX ix_revenue_details_created_at ON revenue_details (created_at);
CREATE INDEX ix_revenue_details_entry_date ON revenue_details (entry_date);

CREATE TABLE bookings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  coach_id INTEGER REFERENCES members (id),
  contract_id INTEGER NOT NULL REFERENCES contracts (id),
  slot_date TEXT NOT NULL,
  slot_start_time TEXT NOT NULL,
  area TEXT NOT NULL CHECK (area IN ('strength', 'pilates')),
  status TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'completed', 'cancelled', 'no_show')),
  created_by_id INTEGER REFERENCES members (id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  venue_coach_id INTEGER REFERENCES venue_rental_coaches (id),
  CHECK ((coach_id IS NOT NULL AND venue_coach_id IS NULL) OR (coach_id IS NULL AND venue_coach_id IS NOT NULL))
);
CREATE UNIQUE INDEX ux_bookings_coach_slot_active ON bookings (coach_id, slot_date, slot_start_time) WHERE status = 'booked' AND coach_id IS NOT NULL;
CREATE UNIQUE INDEX ux_bookings_venue_coach_slot_active ON bookings (venue_coach_id, slot_date, slot_start_time) WHERE status = 'booked' AND venue_coach_id IS NOT NULL;

CREATE TABLE venue_bookings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  venue_coach_id INTEGER NOT NULL REFERENCES venue_rental_coaches (id),
  customer_name TEXT NOT NULL,
  customer_phone TEXT,
  party_size INTEGER NOT NULL DEFAULT 1 CHECK (party_size IN (1, 2)),
  slot_date TEXT NOT NULL,
  slot_start_time TEXT NOT NULL,
  area TEXT NOT NULL CHECK (area = 'strength'),
  status TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'completed', 'cancelled')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  slot_number INTEGER NOT NULL CHECK (slot_number IN (1, 2, 3))
);
CREATE UNIQUE INDEX ux_venue_bookings_slot_active ON venue_bookings (slot_date, slot_start_time, slot_number) WHERE status = 'booked';

CREATE TABLE app_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);

CREATE TABLE cash_movements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_date TEXT NOT NULL,
  movement_type TEXT NOT NULL CHECK (movement_type IN ('petty_cash', 'refund', 'coach_advance', 'advance_return')),
  direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
  amount REAL NOT NULL CHECK (amount > 0),
  counterparty TEXT,
  description TEXT,
  entered_by_id INTEGER NOT NULL REFERENCES admin_users (id),
  voided_at TEXT,
  voided_by_id INTEGER REFERENCES admin_users (id),
  void_reason TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
CREATE INDEX ix_cash_movements_created_at ON cash_movements (created_at);

CREATE TABLE cash_closings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  business_date TEXT NOT NULL,
  shift TEXT NOT NULL CHECK (shift IN ('morning', 'afternoon', 'evening')),
  interval_start TEXT NOT NULL,
  closed_at TEXT NOT NULL,
  opening_cash REAL NOT NULL,
  cash_sales REAL NOT NULL,
  movements_in REAL NOT NULL,
  movements_out REAL NOT NULL,
  expected_cash REAL NOT NULL,
  counted_cash REAL NOT NULL CHECK (counted_cash >= 0),
  denominations TEXT NOT NULL,
  variance REAL NOT NULL,
  collected_amount REAL NOT NULL DEFAULT 0 CHECK (collected_amount >= 0),
  remaining_cash REAL NOT NULL,
  cash_float_snapshot REAL NOT NULL,
  note TEXT,
  closed_by_id INTEGER NOT NULL REFERENCES admin_users (id),
  reviewed_at TEXT,
  reviewed_by_id INTEGER REFERENCES admin_users (id),
  review_note TEXT,
  voided_at TEXT,
  voided_by_id INTEGER REFERENCES admin_users (id),
  void_reason TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
CREATE UNIQUE INDEX ux_cash_closings_date_shift_active ON cash_closings (business_date, shift) WHERE voided_at IS NULL;

-- 匯入舊資料時的「寫入後比對」：同一批指令最後插入一列 ok = 1，筆數不符時 CHECK 失敗、整批不生效
CREATE TABLE import_guard (
  ok INTEGER NOT NULL CHECK (ok = 1)
);
