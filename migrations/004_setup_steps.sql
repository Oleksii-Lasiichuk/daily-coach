-- 004: the first-run window has 5 steps now; 6 = done. Users who finished the old setup stay done.
update users set setup_step = 6 where setup_step >= 5;
