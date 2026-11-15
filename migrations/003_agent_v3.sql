-- 003: v3 — knowledge items (facts with term/until/details), agent actions (undo),
-- reminders + web push, synced health data, user preferences.

alter table facts drop constraint facts_category_check;
alter table facts add constraint facts_category_check check (category in
    ('goal', 'race', 'injury', 'health', 'medication', 'gear', 'preference', 'life', 'lab', 'note'));
alter table facts add column term text not null default 'long' check (term in ('long', 'current'));
alter table facts add column until date;
alter table facts add column details jsonb not null default '{}';

alter table user_secrets drop constraint user_secrets_provider_check;
alter table user_secrets add constraint user_secrets_provider_check
    check (provider in ('intervals', 'openrouter'));

create table user_prefs (
    user_id uuid primary key references users on delete cascade,
    model_default text not null default 'google/gemini-3.8-flash',
    model_deep text not null default 'anthropic/claude-sonnet-5.5',
    nudges jsonb not null default '{"morning": "07:30", "breakfast": "09:00", "lunch": "13:30",
                                    "dinner": "19:30", "evening": "21:30"}',
    nudges_on boolean not null default true,
    updated_at timestamptz not null default now()
);

create table agent_actions (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    message_id bigint references chat_messages on delete cascade,
    tool text not null,
    summary text not null,
    undo jsonb,
    undone boolean not null default false,
    created_at timestamptz not null default now()
);
create index on agent_actions (user_id, message_id);

create table reminders (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    kind text not null default 'custom' check (kind in ('medication', 'custom')),
    text text not null,
    times text[] not null,               -- local "HH:MM"
    until date,
    active boolean not null default true,
    last_sent jsonb not null default '{}', -- {"HH:MM": "YYYY-MM-DD"}
    created_at timestamptz not null default now()
);
create index on reminders (user_id);

create table push_subscriptions (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    endpoint text not null unique,
    p256dh text not null,
    auth text not null,
    created_at timestamptz not null default now()
);

create table nudges_sent (
    user_id uuid not null references users on delete cascade,
    nudge text not null,
    day date not null,
    primary key (user_id, nudge, day)
);

create table wellness_daily (
    user_id uuid not null references users on delete cascade,
    day date not null,
    data jsonb not null,
    primary key (user_id, day)
);

create table activities (
    user_id uuid not null references users on delete cascade,
    id text not null,
    day date not null,
    type text,
    data jsonb not null,
    primary key (user_id, id)
);
create index on activities (user_id, day);

alter table chat_messages add column attachments jsonb not null default '[]';
