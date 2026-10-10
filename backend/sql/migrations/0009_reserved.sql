-- Version 0009 was intentionally unused in the original migration series.
-- Keep an explicit no-op record so operators and automated audits can distinguish
-- a reserved version from an accidentally missing schema change.
SELECT 1;
