-- 006: v7 — chat turns that survive leaving the page; per-person AI access and cap; what each
-- person wants to track (drives the setup cards on Today).

create table chat_turns (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    message_id bigint not null references chat_messages on delete cascade,
    status text not null default 'running' check (status in ('running', 'done', 'failed')),
    reply_id bigint references chat_messages on delete set null,
    error text,
    started_at timestamptz not null default now(),
    finished_at timestamptz
);
create index on chat_turns (user_id, started_at);

-- ai_access: allowed = may use the app's key (up to monthly_cap_usd); blocked = must add an own key.
-- key_pool: which of the app's OpenRouter keys pays ('main' or 'family').
alter table users add column ai_access text not null default 'allowed'
    check (ai_access in ('allowed', 'blocked'));
alter table users add column monthly_cap_usd numeric(8, 2);  -- null = the default for the role
alter table users add column key_pool text not null default 'main'
    check (key_pool in ('main', 'family'));
alter table users add column tracks jsonb not null default '[]';

-- Everyone may use the app's key from now on (a user's own key still wins); caps differ by role.
