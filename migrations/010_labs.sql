-- 010: lab results (B3, C10). One row per marker per sheet; the image/PDF stays only in the chat.
create table lab_results (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    upload_id uuid not null,          -- one sheet; "Undo upload" deletes by it
    taken_on date not null,
    lab text,
    marker text,                      -- canonical key from app/lab_catalog.py, null = unknown
    name_as_printed text not null,
    value numeric,
    qualifier text check (qualifier in ('<', '>')),
    value_text text,                  -- non-numeric results ("negative")
    unit text,
    ref_low numeric,
    ref_high numeric,
    flag text not null default 'unknown' check (flag in ('low', 'high', 'in', 'unknown')),
    source_name text,
    source_message_id bigint references chat_messages on delete set null,  -- the chat upload
    edited boolean not null default false,
    created_at timestamptz not null default now()
);
create index on lab_results (user_id, marker, taken_on);
