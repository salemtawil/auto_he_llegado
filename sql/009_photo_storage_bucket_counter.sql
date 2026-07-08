alter table public.photos
add column if not exists storage_bucket text;

update public.photos p
set storage_bucket = 'photo-pool'
where p.storage_bucket is null
and exists (
    select 1
      from public.photo_candidates c
      where c.approved_photo_id = p.id
  );

update public.photos
set storage_bucket = 'photo-pool'
where storage_bucket is null;

create index if not exists idx_photos_available_storage_bucket
on public.photos (status, storage_bucket)
where storage_deleted_at is null;

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
        count(*) filter (where storage_bucket = p_active_bucket)::bigint as new_bucket_count,
        count(*) filter (
            where storage_bucket is null
               or (p_legacy_bucket is not null and storage_bucket = p_legacy_bucket)
        )::bigint as old_bucket_count
    from public.photos
    where status = 'available'
      and storage_deleted_at is null;
$$;
