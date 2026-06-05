-- No-op migration kept so existing migration history remains monotonic.
-- Legacy schema rename is handled in sql/apply.py before migrations run.
SELECT 1;
