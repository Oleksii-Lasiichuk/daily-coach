-- 002: separate setup flow + user files (sources) for retrieval (C4).

alter table users add column setup_step int not null default 1;  -- 1..4, 5 = done

create extension if not exists vector;

create table sources (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    filename text not null,
    bytes int not null,
    status text not null default 'reading' check (status in ('reading', 'done', 'error')),
    n_chunks int not null default 0,
    n_processed int not null default 0,
    error text,
    created_at timestamptz not null default now()
);
create index on sources (user_id);

create table chunks (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    source_id bigint not null references sources on delete cascade,
    idx int not null,
    text text not null,
    embedding vector(768),
    unique (source_id, idx)
);
create index on chunks (user_id);
create index on chunks using hnsw (embedding vector_cosine_ops);

-- Facts proposed from files wait for the user's confirmation; they keep the quote and source.
alter table facts drop constraint facts_status_check;
alter table facts add constraint facts_status_check
    check (status in ('proposed', 'active', 'resolved'));
alter table facts drop constraint facts_source_check;
alter table facts add constraint facts_source_check check (source in ('user', 'ai', 'file'));
alter table facts add column source_id bigint references sources on delete cascade;
alter table facts add column quote text;

-- Users who already chatted are past setup.
update users set setup_step = 5 where exists (select 1 from chat_messages m where m.user_id = users.id);
