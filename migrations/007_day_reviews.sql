-- 007: the coach's nutrition review of a day (C9), cached until that day's logs change.
create table day_reviews (
    user_id uuid not null references users on delete cascade,
    day date not null,
    lang text not null,
    input_hash text not null,  -- of the numbers the review was written from
    review jsonb not null,
    created_at timestamptz not null default now(),
    primary key (user_id, day, lang)
);
