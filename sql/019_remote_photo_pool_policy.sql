create table if not exists public.app_settings (
    key text primary key,
    value jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default timezone('utc', now())
);

alter table public.app_settings enable row level security;

drop policy if exists "app_settings_admin_select" on public.app_settings;
create policy "app_settings_admin_select"
on public.app_settings for select
to authenticated
using (public.is_profile_admin(auth.uid()));

drop policy if exists "app_settings_admin_update" on public.app_settings;
create policy "app_settings_admin_update"
on public.app_settings for update
to authenticated
using (public.is_profile_admin(auth.uid()))
with check (public.is_profile_admin(auth.uid()));

drop policy if exists "app_settings_admin_insert" on public.app_settings;
create policy "app_settings_admin_insert"
on public.app_settings for insert
to authenticated
with check (public.is_profile_admin(auth.uid()));

insert into public.app_settings (key, value)
values (
    'photo_pool',
    '{"bucket": "photo-pool", "available_prefix": "available", "candidates_prefix": "candidates"}'::jsonb
)
on conflict (key) do nothing;

create or replace function public.get_photo_pool_policy()
returns table(bucket text, available_prefix text, candidates_prefix text)
language sql
stable
security definer
set search_path = public
as $$
    select
        coalesce(nullif(trim(s.value->>'bucket'), ''), 'photo-pool') as bucket,
        coalesce(nullif(trim(s.value->>'available_prefix'), ''), 'available') as available_prefix,
        coalesce(nullif(trim(s.value->>'candidates_prefix'), ''), 'candidates') as candidates_prefix
    from public.app_settings s
    where s.key = 'photo_pool'
    union all
    select 'photo-pool', 'available', 'candidates'
    where not exists (
        select 1
        from public.app_settings s
        where s.key = 'photo_pool'
    )
    limit 1;
$$;

grant execute on function public.get_photo_pool_policy() to anon, authenticated;

create or replace function public.active_photo_pool_bucket()
returns text
language sql
stable
security definer
set search_path = public
as $$
    select bucket
    from public.get_photo_pool_policy()
    limit 1;
$$;

grant execute on function public.active_photo_pool_bucket() to anon, authenticated;

create or replace function public.list_photo_pool_buckets()
returns table(bucket text)
language sql
stable
security definer
set search_path = public, storage
as $$
    select b.id::text as bucket
    from storage.buckets b
    order by b.id::text;
$$;

grant execute on function public.list_photo_pool_buckets() to authenticated;

drop policy if exists "photo_candidate_storage_insert" on storage.objects;
create policy "photo_candidate_storage_insert"
on storage.objects for insert
to authenticated
with check (
    bucket_id = public.active_photo_pool_bucket()
    and (storage.foldername(name))[1] = 'candidates'
    and (storage.foldername(name))[2] = auth.uid()::text
    and public.can_submit_weekly_video(auth.uid())
);

drop policy if exists "photo_candidate_storage_select" on storage.objects;
create policy "photo_candidate_storage_select"
on storage.objects for select
to authenticated
using (
    bucket_id = public.active_photo_pool_bucket()
    and (
        public.is_profile_admin(auth.uid())
        or (storage.foldername(name))[1] = 'available'
        or (
            (storage.foldername(name))[1] = 'candidates'
            and (storage.foldername(name))[2] = auth.uid()::text
        )
    )
);

drop policy if exists "photo_admin_storage_write" on storage.objects;
create policy "photo_admin_storage_write"
on storage.objects for all
to authenticated
using (bucket_id = public.active_photo_pool_bucket() and public.is_profile_admin(auth.uid()))
with check (bucket_id = public.active_photo_pool_bucket() and public.is_profile_admin(auth.uid()));

create or replace function public.claim_available_photo(
    p_process_id text default null,
    p_validate_only boolean default false,
    p_active_bucket text default null
)
returns setof public.photos
language plpgsql
as $$
declare
    claimed_record public.photos%rowtype;
    v_active_bucket text;
begin
    v_active_bucket := coalesce(nullif(p_active_bucket, ''), 'photo-pool');

    if p_validate_only then
        return;
    end if;

    select p.*
    into claimed_record
    from public.photos p
    where p.status = 'available'
      and p.storage_deleted_at is null
      and p.file_path is not null
      and coalesce(nullif(p.storage_bucket, ''), v_active_bucket) = v_active_bucket
      and exists (
          select 1
          from storage.objects o
          where o.bucket_id = v_active_bucket
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

create or replace function public.photo_pool_counts(
    p_active_bucket text default null,
    p_legacy_bucket text default null
)
returns table(available_count bigint, new_bucket_count bigint, old_bucket_count bigint)
language sql
stable
security definer
set search_path = public
as $$
    with policy as (
        select coalesce(nullif(p_active_bucket, ''), public.active_photo_pool_bucket()) as active_bucket
    )
    select
        count(*)::bigint as available_count,
        count(*) filter (where p.storage_bucket = policy.active_bucket)::bigint as new_bucket_count,
        count(*) filter (
            where p.storage_bucket is null
               or (p_legacy_bucket is not null and p.storage_bucket = p_legacy_bucket)
        )::bigint as old_bucket_count
    from public.photos p, policy
    where p.status = 'available'
      and p.storage_deleted_at is null
      and p.file_path is not null
      and coalesce(nullif(p.storage_bucket, ''), policy.active_bucket) = policy.active_bucket
      and exists (
          select 1
          from storage.objects o
          where o.bucket_id = policy.active_bucket
            and o.name = p.file_path
      );
$$;

grant execute on function public.photo_pool_counts(text, text) to authenticated;

notify pgrst, 'reload schema';
