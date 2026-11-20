-- 011: money (plan 11, B4). Monobank personal API accounts, the webhook token (hashed),
-- transactions (Monobank rows and receipts; receipt lines are children via parent_id) and
-- per-user merchant rules (the person's corrections and cached C11 answers).
-- Not stored on purpose: comment, counterIban/Edrpou/Name, balance, receiptId, IBAN, full
-- card number, the client's name.

-- Full provider list (B2's 009 writes the same list, so the order of 009/011 doesn't matter).
alter table user_secrets drop constraint user_secrets_provider_check;
alter table user_secrets add constraint user_secrets_provider_check
    check (provider in ('intervals', 'openrouter', 'ical', 'monobank', 'garmin'));

create table money_accounts (
    user_id uuid not null references users on delete cascade,
    account_id text not null,          -- Monobank account id (an API handle, not the IBAN)
    kind text not null,                -- black, white, fop, …
    currency int not null,
    last4 text,
    import_since timestamptz not null, -- how far back the person chose (default 6 months)
    imported_from timestamptz,         -- oldest time imported so far
    synced_until timestamptz,          -- newest time covered by a statement call
    next_at timestamptz not null default now(),
    primary key (user_id, account_id)
);

create table money_hooks (
    hook_hash text primary key,        -- sha256 of the token in the webhook URL
    user_id uuid not null unique references users on delete cascade
);

create table transactions (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    source text not null check (source in ('monobank', 'receipt')),
    ext_id text,                        -- Monobank id
    account_id text,
    at timestamptz not null,
    amount_minor bigint not null,       -- negative = spending, in account currency
    currency int not null default 980,
    mcc int,
    original_mcc int,
    description text,
    hold boolean not null default false,
    category text,
    category_by text check (category_by in ('rule', 'llm', 'user', 'receipt')),
    parent_id bigint references transactions on delete cascade,  -- receipt split lines
    unique (user_id, source, ext_id)
);
create index on transactions (user_id, at);

create table merchant_rules (
    user_id uuid not null references users on delete cascade,
    merchant text not null,             -- normalised description
    category text not null,
    by text not null check (by in ('llm', 'user')),
    primary key (user_id, merchant)
);
