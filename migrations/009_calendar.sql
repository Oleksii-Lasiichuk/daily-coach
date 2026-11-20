-- 009: B2 calendar through an iCal (ICS) link. The ICS URL is a credential: it lives encrypted in
-- user_secrets (provider 'ical'). Busy blocks for -1..+14 days, replaced on every sync.
-- The provider list is written in full so B4 (011) and B5 (012) cannot drop each other's value.

alter table user_secrets drop constraint user_secrets_provider_check;
alter table user_secrets add constraint user_secrets_provider_check
    check (provider in ('intervals', 'openrouter', 'ical', 'monobank', 'garmin'));

create table calendar_feeds (
    user_id uuid primary key references users on delete cascade,
    show_titles boolean not null default false,
    next_at timestamptz not null default now(),
    last_ok_at timestamptz,
    last_error text,
    event_count int not null default 0
);

create table calendar_blocks (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    starts_at timestamptz not null,
    ends_at timestamptz not null,
    all_day boolean not null default false,
    title text,                       -- null unless calendar_feeds.show_titles
    check (ends_at > starts_at)
);
create index on calendar_blocks (user_id, starts_at);
