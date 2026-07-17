-- Real Supabase Storage usage audit.
-- Apply this file in the Supabase SQL Editor when you need the app to show
-- actual Storage usage by bucket and top-level folder.

create or replace function public.storage_usage_by_prefix()
returns table (
    bucket_name text,
    top_folder text,
    object_count bigint,
    total_bytes bigint
)
language sql
security definer
set search_path = public, storage
as $$
    select
        o.bucket_id::text as bucket_name,
        coalesce(nullif(split_part(o.name, '/', 1), ''), '(raiz)')::text as top_folder,
        count(*)::bigint as object_count,
        coalesce(sum(coalesce((o.metadata->>'size')::bigint, 0)), 0)::bigint as total_bytes
    from storage.objects o
    group by o.bucket_id, coalesce(nullif(split_part(o.name, '/', 1), ''), '(raiz)')
    order by total_bytes desc, object_count desc;
$$;

grant execute on function public.storage_usage_by_prefix() to authenticated;

create or replace function public.candidate_storage_usage_by_status()
returns table (
    candidate_status text,
    object_count bigint,
    linked_storage_count bigint,
    total_bytes bigint
)
language sql
security definer
set search_path = public, storage
as $$
    select
        c.status::text as candidate_status,
        count(*)::bigint as object_count,
        count(o.id)::bigint as linked_storage_count,
        coalesce(sum(coalesce((o.metadata->>'size')::bigint, 0)), 0)::bigint as total_bytes
    from public.photo_candidates c
    left join storage.objects o
        on o.name = c.storage_path
    group by c.status
    order by total_bytes desc, object_count desc;
$$;

grant execute on function public.candidate_storage_usage_by_status() to authenticated;

create or replace function public.available_storage_orphan_audit()
returns table (
    bucket_name text,
    object_count bigint,
    total_bytes bigint
)
language sql
security definer
set search_path = public, storage
as $$
    select
        o.bucket_id::text as bucket_name,
        count(*)::bigint as object_count,
        coalesce(sum(coalesce((o.metadata->>'size')::bigint, 0)), 0)::bigint as total_bytes
    from storage.objects o
    left join public.photos p
        on p.storage_bucket = o.bucket_id
       and p.file_path = o.name
       and p.storage_deleted_at is null
    where split_part(o.name, '/', 1) = 'available'
      and p.id is null
    group by o.bucket_id
    order by total_bytes desc, object_count desc;
$$;

grant execute on function public.available_storage_orphan_audit() to authenticated;

create or replace function public.available_storage_orphan_paths(p_limit integer default 1000)
returns table (
    bucket_name text,
    storage_path text,
    total_bytes bigint
)
language sql
security definer
set search_path = public, storage
as $$
    select
        o.bucket_id::text as bucket_name,
        o.name::text as storage_path,
        coalesce((o.metadata->>'size')::bigint, 0)::bigint as total_bytes
    from storage.objects o
    left join public.photos p
        on p.storage_bucket = o.bucket_id
       and p.file_path = o.name
       and p.storage_deleted_at is null
    where split_part(o.name, '/', 1) = 'available'
      and p.id is null
    order by o.name
    limit greatest(1, least(coalesce(p_limit, 1000), 1000));
$$;

grant execute on function public.available_storage_orphan_paths(integer) to authenticated;
