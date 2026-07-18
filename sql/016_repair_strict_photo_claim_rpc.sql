-- Repair the photo claim RPC expected by the app.
--
-- Use this when the app says claim_available_photo is missing, even after
-- applying the strict photo pool SQL. It removes the older 2-argument overload
-- so PostgREST has a single, unambiguous RPC signature.

drop function if exists public.claim_available_photo(text, boolean);

create or replace function public.claim_available_photo(
    p_process_id text default null,
    p_validate_only boolean default false,
    p_active_bucket text default 'photo-pool'
)
returns setof public.photos
language plpgsql
as $$
declare
    claimed_record public.photos%rowtype;
begin
    if p_validate_only then
        return;
    end if;

    select p.*
    into claimed_record
    from public.photos p
    where p.status = 'available'
      and p.storage_deleted_at is null
      and p.file_path is not null
      and exists (
          select 1
          from storage.objects o
          where o.bucket_id = coalesce(nullif(p.storage_bucket, ''), p_active_bucket)
            and o.name = p.file_path
      )
    order by random()
    for update skip locked
    limit 1;

    if not found then
        return;
    end if;

    update public.photos
    set
        status = 'reserved',
        reserved_at = timezone('utc', now()),
        reserved_by_process_id = p_process_id
    where id = claimed_record.id
      and status = 'available'
    returning *
    into claimed_record;

    if not found then
        return;
    end if;

    return next claimed_record;
end;
$$;

grant execute on function public.claim_available_photo(text, boolean, text) to authenticated;

notify pgrst, 'reload schema';
