-- Photo pool integrity cleanup.
-- Discards DB rows marked as available when the Storage object is missing.

create or replace function public.missing_available_photo_audit(
    p_active_bucket text default 'photo-pool'
)
returns table (
    missing_count bigint
)
language sql
stable
as $$
    select count(*)::bigint as missing_count
    from public.photos p
    where p.status = 'available'
      and p.storage_deleted_at is null
      and p.file_path is not null
      and not exists (
          select 1
          from storage.objects o
          where o.bucket_id = coalesce(nullif(p.storage_bucket, ''), p_active_bucket)
            and o.name = p.file_path
      );
$$;

grant execute on function public.missing_available_photo_audit(text) to authenticated;

create or replace function public.discard_missing_available_photos(
    p_active_bucket text default 'photo-pool',
    p_limit integer default 1000,
    p_reason text default 'missing_storage_integrity_cleanup',
    p_cleaned_by text default 'admin_cleanup'
)
returns table (
    photo_id uuid,
    storage_bucket text,
    file_path text
)
language plpgsql
as $$
begin
    return query
    with targets as (
        select p.id
        from public.photos p
        where p.status = 'available'
          and p.storage_deleted_at is null
          and p.file_path is not null
          and not exists (
              select 1
              from storage.objects o
              where o.bucket_id = coalesce(nullif(p.storage_bucket, ''), p_active_bucket)
                and o.name = p.file_path
          )
        order by p.created_at nulls first, p.id
        limit greatest(1, least(coalesce(p_limit, 1000), 1000))
        for update skip locked
    )
    update public.photos p
    set
        status = 'discarded',
        storage_deleted_at = timezone('utc', now()),
        cleanup_reason = p_reason,
        cleanup_error = null,
        cleaned_by = p_cleaned_by,
        reserved_at = null,
        reserved_by_process_id = null
    from targets t
    where p.id = t.id
    returning p.id, p.storage_bucket, p.file_path;
end;
$$;

grant execute on function public.discard_missing_available_photos(text, integer, text, text) to authenticated;
