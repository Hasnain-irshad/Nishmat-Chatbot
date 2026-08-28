-- =============================================================================
-- Postgres-backed job queue.
--
-- No Redis, no Celery. `FOR UPDATE SKIP LOCKED` gives us safe concurrent
-- claiming in ~40 lines of SQL, the queue survives a redeploy because it is
-- just a table, and job state is queryable with the same tools as everything
-- else. If throughput ever demands more, only `app/jobs/queue.py` changes.
-- =============================================================================

-- Claim exactly one queued job, atomically.
--
-- SKIP LOCKED is what makes this safe to run from several workers at once:
-- each transaction takes a different row instead of blocking on the same one.
create or replace function claim_job(
  p_worker text,
  p_types  text[] default null
)
returns setof jobs
language plpgsql
security definer
set search_path = public
as $$
begin
  return query
  update jobs
  set status     = 'running',
      locked_at  = now(),
      locked_by  = p_worker,
      attempts   = jobs.attempts + 1,
      updated_at = now()
  where jobs.id = (
    select j.id
    from jobs j
    where j.status = 'queued'
      and (p_types is null or j.type = any(p_types))
    order by j.created_at
    for update skip locked
    limit 1
  )
  returning jobs.*;
end;
$$;


create or replace function complete_job(
  p_job_id uuid,
  p_result jsonb default '{}'::jsonb
)
returns void
language sql
security definer
set search_path = public
as $$
  update jobs
  set status         = 'succeeded',
      result         = p_result,
      progress_pct   = 100,
      progress_stage = 'done',
      locked_at      = null,
      locked_by      = null,
      error          = null,
      updated_at     = now()
  where id = p_job_id;
$$;


-- Fail a job, retrying it if attempts remain.
--
-- `attempts` was already incremented at claim time, so a job that has used up
-- its allowance lands in 'failed' and stops; anything else goes back to the
-- queue for another worker.
create or replace function fail_job(
  p_job_id uuid,
  p_error  text,
  p_retry  boolean default true
)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_attempts integer;
  v_max      integer;
  v_status   text;
begin
  select attempts, max_attempts into v_attempts, v_max
  from jobs where id = p_job_id;

  if v_attempts is null then
    return 'missing';
  end if;

  if p_retry and v_attempts < v_max then
    v_status := 'queued';
  else
    v_status := 'failed';
  end if;

  update jobs
  set status     = v_status::job_status,
      error      = left(p_error, 2000),
      locked_at  = null,
      locked_by  = null,
      updated_at = now()
  where id = p_job_id;

  return v_status;
end;
$$;


create or replace function update_job_progress(
  p_job_id uuid,
  p_stage  text,
  p_pct    integer default null
)
returns void
language sql
security definer
set search_path = public
as $$
  update jobs
  set progress_stage = p_stage,
      progress_pct   = coalesce(least(greatest(p_pct, 0), 100), progress_pct),
      updated_at     = now()
  where id = p_job_id;
$$;


-- Requeue jobs whose worker died mid-run.
--
-- Without this a crashed worker leaves its job 'running' forever and the
-- admin sees a spinner that never resolves.
create or replace function reap_stale_jobs(
  p_timeout_seconds integer default 900
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_count integer;
begin
  with stale as (
    update jobs
    set status     = case
                       when attempts >= max_attempts then 'failed'::job_status
                       else 'queued'::job_status
                     end,
        error      = 'Worker stopped responding; job was requeued',
        locked_at  = null,
        locked_by  = null,
        updated_at = now()
    where status = 'running'
      and locked_at < now() - make_interval(secs => p_timeout_seconds)
    returning 1
  )
  select count(*) into v_count from stale;
  return v_count;
end;
$$;


-- Workers run as the service role. Nothing here is callable by a browser.
revoke all on function claim_job          from public, anon, authenticated;
revoke all on function complete_job       from public, anon, authenticated;
revoke all on function fail_job           from public, anon, authenticated;
revoke all on function update_job_progress from public, anon, authenticated;
revoke all on function reap_stale_jobs    from public, anon, authenticated;
