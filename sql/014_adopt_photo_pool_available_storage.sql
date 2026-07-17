-- Adopt existing Storage objects from one bucket into public.photos.
-- Use this after cleanup when Storage still has usable JPG files but the app
-- counter is 0 because there are no active rows in public.photos.

create or replace function public.adopt_available_storage_objects(
    p_bucket text default 'photo-pool',
    p_limit integer default 1000
)
returns table (
    photo_id uuid,
    storage_bucket text,
    file_path text
)
language sql
security definer
set search_path = public, storage
as $$
    insert into public.photos (
        id,
        original_name,
        file_path,
        status,
        storage_bucket
    )
    select
        gen_random_uuid(),
        reverse(split_part(reverse(o.name), '/', 1)) as original_name,
        o.name as file_path,
        'available' as status,
        o.bucket_id as storage_bucket
    from storage.objects o
    left join public.photos p
        on p.storage_bucket = o.bucket_id
       and p.file_path = o.name
       and p.storage_deleted_at is null
    where o.bucket_id = p_bucket
      and split_part(o.name, '/', 1) = 'available'
      and p.id is null
    order by o.name
    limit greatest(1, least(coalesce(p_limit, 1000), 1000))
    returning id, storage_bucket, file_path;
$$;

grant execute on function public.adopt_available_storage_objects(text, integer) to authenticated;

create or replace function public.adoptable_available_storage_audit(
    p_bucket text default 'photo-pool'
)
returns table (
    bucket_name text,
    adoptable_count bigint
)
language sql
stable
security definer
set search_path = public, storage
as $$
    select
        o.bucket_id::text as bucket_name,
        count(*)::bigint as adoptable_count
    from storage.objects o
    left join public.photos p
        on p.storage_bucket = o.bucket_id
       and p.file_path = o.name
       and p.storage_deleted_at is null
    where o.bucket_id = p_bucket
      and split_part(o.name, '/', 1) = 'available'
      and p.id is null
    group by o.bucket_id;
$$;

grant execute on function public.adoptable_available_storage_audit(text) to authenticated;
