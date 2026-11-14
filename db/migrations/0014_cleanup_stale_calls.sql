-- Migration 0014: Clean up historical orphaned calls stuck with ended_at IS NULL
-- (Bug 1.5: Calls that crashed during setup stayed "in progress" and counted towards concurrent limits)

update calls
set ended_at = started_at,
    outcome = 'dropped'
where ended_at is null
  and started_at < now() - interval '1 hour';
