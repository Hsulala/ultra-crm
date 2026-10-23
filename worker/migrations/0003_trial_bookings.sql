-- 體驗課預約：不需要合約，填姓名電話；佔教練時段（皮拉提斯也佔名額），同時記一筆體驗費營收
CREATE TABLE trial_bookings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  coach_id INTEGER NOT NULL REFERENCES members (id),
  area TEXT NOT NULL CHECK (area IN ('strength', 'pilates')),
  slot_date TEXT NOT NULL,
  slot_start_time TEXT NOT NULL,
  customer_name TEXT NOT NULL,
  customer_phone TEXT,
  fee REAL NOT NULL DEFAULT 0,
  revenue_id INTEGER REFERENCES revenue_details (id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'cancelled')),
  created_by_admin_id INTEGER REFERENCES admin_users (id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
CREATE UNIQUE INDEX ux_trial_bookings_coach_slot ON trial_bookings (coach_id, slot_date, slot_start_time) WHERE status = 'booked';
CREATE INDEX ix_trial_bookings_date ON trial_bookings (slot_date);
