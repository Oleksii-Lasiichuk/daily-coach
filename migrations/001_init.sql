-- 001: initial schema. Every personal table has user_id; times are UTC (timestamptz),
-- days are dates in the user's time zone.

create table users (
    id uuid primary key default gen_random_uuid(),
    firebase_uid text not null unique,
    email text not null unique,
    display_name text,
    time_zone text not null default 'Europe/Kyiv',
    created_at timestamptz not null default now()
);

create table user_secrets (
    user_id uuid not null references users on delete cascade,
    provider text not null check (provider in ('intervals')),
    ciphertext text not null,
    last4 text not null,
    external_id text,
    created_at timestamptz not null default now(),
    primary key (user_id, provider)
);

create table profile_fields (
    user_id uuid not null references users on delete cascade,
    key text not null,
    value jsonb not null,
    source text not null check (source in ('intervals', 'user', 'ai')),
    updated_at timestamptz not null default now(),
    primary key (user_id, key)
);

create table chat_messages (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    trace_id text,
    created_at timestamptz not null default now()
);
create index on chat_messages (user_id, created_at);

create table facts (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    category text not null check (category in
        ('health', 'injury', 'medication', 'goal', 'race', 'gear', 'preference', 'life')),
    text text not null,
    status text not null default 'active' check (status in ('active', 'resolved')),
    valid_from date,
    valid_to date,
    source text not null check (source in ('user', 'ai')),
    message_id bigint references chat_messages on delete set null,
    created_at timestamptz not null default now()
);
create index on facts (user_id, status);

create table logs (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    kind text not null check (kind in ('meal', 'drink', 'alcohol', 'sleep', 'mood', 'pain',
        'symptom', 'medication', 'activity', 'planned_workout', 'note')),
    day date not null,
    occurred_at timestamptz,
    data jsonb not null default '{}',
    message_id bigint references chat_messages on delete set null,
    created_at timestamptz not null default now()
);
create index on logs (user_id, day);

create table day_assessments (
    user_id uuid not null references users on delete cascade,
    day date not null,
    day_type text not null check (day_type in ('recover', 'easy', 'normal', 'push')),
    confidence real,
    reasons jsonb not null default '[]',
    inputs jsonb not null default '{}',
    trace_id text,
    created_at timestamptz not null default now(),
    primary key (user_id, day)
);

create table proposals (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    day date not null,
    status text not null default 'proposed'
        check (status in ('proposed', 'applied', 'undone', 'dismissed')),
    workout jsonb not null,
    rationale text not null,
    evidence jsonb not null default '[]',
    intervals_event_id text,
    created_at timestamptz not null default now(),
    applied_at timestamptz
);
create index on proposals (user_id, day);

create table llm_usage (
    id bigint generated always as identity primary key,
    user_id uuid references users on delete cascade,
    component text not null,
    model text not null,
    input_tokens int not null,
    output_tokens int not null,
    cost_usd numeric(10, 6) not null,
    created_at timestamptz not null default now()
);
create index on llm_usage (user_id, created_at);

create table audit_log (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    actor text not null check (actor in ('user', 'ai', 'system')),
    action text not null,
    entity text not null,
    entity_id text,
    before jsonb,
    after jsonb,
    created_at timestamptz not null default now()
);
