-- 005: v4 — UI language, habits checklist.

alter table user_prefs add column lang text not null default 'en' check (lang in ('en', 'uk'));

create table habits (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    name text not null,
    active boolean not null default true,
    created_at timestamptz not null default now()
);
create index on habits (user_id);

create table habit_checks (
    user_id uuid not null references users on delete cascade,
    habit_id bigint not null references habits on delete cascade,
    day date not null,
    primary key (habit_id, day)
);
create index on habit_checks (user_id, day);
