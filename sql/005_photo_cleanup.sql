alter table public.photos
add column if not exists storage_deleted_at timestamptz;

alter table public.photos
add column if not exists cleanup_reason text;

alter table public.photos
add column if not exists cleanup_error text;

alter table public.photos
add column if not exists cleaned_by text;

do $$
declare
    status_type text;
    status_udt_name text;
begin
    select c.data_type, c.udt_name
    into status_type, status_udt_name
    from information_schema.columns as c
    where c.table_schema = 'public'
      and c.table_name = 'photos'
      and c.column_name = 'status'
    limit 1;

    if status_type = 'USER-DEFINED' and status_udt_name is not null then
        if not exists (
            select 1
            from pg_enum e
            join pg_type t on t.oid = e.enumtypid
            join pg_namespace n on n.oid = t.typnamespace
            where n.nspname = 'public'
              and t.typname = status_udt_name
              and e.enumlabel = 'discarded'
        ) then
            execute format(
                'alter type %I.%I add value if not exists %L',
                'public',
                status_udt_name,
                'discarded'
            );
        end if;
    end if;
end
$$;

create or replace function public.photo_cleanup_audit(
    p_older_than_hours integer default 2
)
returns table (
    available_count bigint,
    reserved_count bigint,
    consumed_count bigint,
    discarded_count bigint,
    consumed_pending_storage_cleanup bigint,
    consumed_cleanable_pending_storage_cleanup bigint,
    stale_reserved_pending_storage_cleanup bigint,
    stale_reserved_cleanable_pending_storage_cleanup bigint,
    storage_cleaned_count bigint,
    consumed_storage_cleaned_count bigint,
    stale_reserved_storage_cleaned_count bigint,
    cleanup_error_count bigint,
    db_error_after_storage_delete_count bigint
)
language sql
stable
as $$
    with base as (
        select *
        from public.photos
    ),
    stale_cutoff as (
        select now() - (greatest(coalesce(p_older_than_hours, 2), 1)::text || ' hours')::interval as value
    )
    select
        count(*) filter (where status = 'available')::bigint,
        count(*) filter (where status = 'reserved')::bigint,
        count(*) filter (where status = 'consumed')::bigint,
        count(*) filter (where status = 'discarded')::bigint,
        count(*) filter (
            where status = 'consumed'
              and file_path is not null
              and storage_deleted_at is null
        )::bigint,
        count(*) filter (
            where status = 'consumed'
              and file_path is not null
              and storage_deleted_at is null
              and cleanup_error is null
        )::bigint,
        count(*) filter (
            where status = 'reserved'
              and file_path is not null
              and storage_deleted_at is null
              and reserved_at is not null
              and reserved_at < (select value from stale_cutoff)
        )::bigint,
        count(*) filter (
            where status = 'reserved'
              and file_path is not null
              and storage_deleted_at is null
              and cleanup_error is null
              and reserved_at is not null
              and reserved_at < (select value from stale_cutoff)
        )::bigint,
        count(*) filter (where storage_deleted_at is not null)::bigint,
        count(*) filter (where status = 'consumed' and storage_deleted_at is not null)::bigint,
        count(*) filter (where status = 'discarded' and storage_deleted_at is not null)::bigint,
        count(*) filter (where cleanup_error is not null)::bigint,
        count(*) filter (
            where file_path is not null
              and storage_deleted_at is null
              and cleanup_error like 'Storage borrado, pero fallo update DB:%'
        )::bigint
    from base;
$$;
