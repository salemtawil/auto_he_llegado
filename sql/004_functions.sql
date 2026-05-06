alter table if exists public.photos
add column if not exists reserved_by_process_id text;

create index if not exists idx_photos_reserved_by_process_id
on public.photos (reserved_by_process_id);

create or replace function public.claim_available_photo(
    p_process_id text default null,
    p_validate_only boolean default false
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

    select *
    into claimed_record
    from public.photos
    where status = 'available'
    order by created_at nulls first, id
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
