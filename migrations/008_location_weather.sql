-- B1 (plan 11): location and richer weather.
-- 'HH:MM' local times, set in Settings only (not on the welcome screen); defaults in code:
-- training 07:00, wake 07:00, bedtime 22:30.
alter table user_prefs add column usual_training_time text;
alter table user_prefs add column wake_time text;
alter table user_prefs add column bedtime text;
alter table user_prefs add column location_auto boolean not null default true;
