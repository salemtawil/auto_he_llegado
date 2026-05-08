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
