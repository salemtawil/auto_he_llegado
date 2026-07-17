-- Strict photo pool claim.
-- This version only reserves photos that still have a real Storage object.

create index if not exists idx_photos_available_claimable
on public.photos (status, storage_bucket, file_path)
where storage_deleted_at is null;

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

create or replace function public.photo_pool_counts(
    p_active_bucket text,
    p_legacy_bucket text default null
)
returns table (
    available_count bigint,
    new_bucket_count bigint,
    old_bucket_count bigint
)
language sql
stable
as $$
    select
        count(*)::bigint as available_count,
        count(*) filter (where p.storage_bucket = p_active_bucket)::bigint as new_bucket_count,
        count(*) filter (
            where p.storage_bucket is null
               or (p_legacy_bucket is not null and p.storage_bucket = p_legacy_bucket)
        )::bigint as old_bucket_count
    from public.photos p
    where p.status = 'available'
      and p.storage_deleted_at is null
      and p.file_path is not null
      and exists (
          select 1
          from storage.objects o
          where o.bucket_id = coalesce(nullif(p.storage_bucket, ''), p_active_bucket)
            and o.name = p.file_path
      );
$$;

grant execute on function public.claim_available_photo(text, boolean, text) to authenticated;
grant execute on function public.photo_pool_counts(text, text) to authenticated;
