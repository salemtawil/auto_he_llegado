create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    email text not null unique,
    login_id text,
    display_name text not null default '',
    role text not null default 'member' check (role in ('member', 'admin')),
    approved boolean not null default false,
    disabled boolean not null default false,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.photo_ingest_batches (
    id uuid primary key,
    user_id uuid not null references auth.users(id) on delete cascade,
    week_start date not null,
    original_video_name text not null,
    frames_extracted integer not null default 0,
    candidates_uploaded integer not null default 0,
    approved_count integer not null default 0,
    rejected_count integer not null default 0,
    status text not null default 'processing'
        check (status in ('processing', 'pending_review', 'accepted', 'rejected', 'reviewed')),
    error_message text,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.photo_candidates (
    id uuid primary key,
    batch_id uuid not null references public.photo_ingest_batches(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    storage_path text not null,
    original_name text not null,
    frame_index integer not null default 0,
    timestamp_seconds numeric not null default 0,
    blur_score numeric,
    brightness_score numeric,
    status text not null default 'pending'
        check (status in ('pending', 'approved', 'rejected', 'deleted')),
    reviewed_by uuid references auth.users(id),
    reviewed_at timestamptz,
    rejection_reason text,
    approved_photo_id uuid,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_photo_ingest_batches_user_week
on public.photo_ingest_batches (user_id, week_start);

create index if not exists idx_photo_ingest_batches_status
on public.photo_ingest_batches (status, created_at desc);

create index if not exists idx_photo_candidates_batch_status
on public.photo_candidates (batch_id, status);

create index if not exists idx_photo_candidates_status_created
on public.photo_candidates (status, created_at desc);

create unique index if not exists idx_profiles_login_id_unique
on public.profiles (lower(login_id))
where login_id is not null and login_id <> '';

create or replace function public.handle_new_auth_user_profile()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id, email, login_id, display_name)
    values (
        new.id,
        coalesce(nullif(new.email, ''), new.id::text),
        nullif(lower(new.raw_user_meta_data->>'login_id'), ''),
        coalesce(new.raw_user_meta_data->>'display_name', '')
    )
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created_profile on auth.users;
create trigger on_auth_user_created_profile
after insert on auth.users
for each row execute function public.handle_new_auth_user_profile();

create or replace function public.resolve_login_identifier(p_identifier text)
returns table(email text)
language sql
stable
security definer
set search_path = public
as $$
    select p.email
    from public.profiles p
    where lower(p.login_id) = lower(trim(p_identifier))
       or lower(p.email) = lower(trim(p_identifier))
    limit 1;
$$;

grant execute on function public.resolve_login_identifier(text) to anon, authenticated;

create or replace function public.is_profile_admin(p_user_id uuid default auth.uid())
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
        from public.profiles p
        where p.id = p_user_id
          and p.role = 'admin'
          and p.approved = true
          and p.disabled = false
    );
$$;

create or replace function public.has_current_week_contribution(
    p_user_id uuid default auth.uid(),
    p_week_start date default date_trunc('week', timezone('utc', now()))::date
)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
        from public.photo_ingest_batches b
        where b.user_id = p_user_id
          and b.week_start = p_week_start
          and b.status in ('processing', 'pending_review', 'accepted', 'reviewed')
    );
$$;

create or replace function public.can_submit_weekly_video(p_user_id uuid default auth.uid())
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
        from public.profiles p
        where p.id = p_user_id
          and p.approved = true
          and p.disabled = false
    );
$$;

create or replace function public.is_active_member(
    p_user_id uuid default auth.uid(),
    p_week_start date default date_trunc('week', timezone('utc', now()))::date
)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
        from public.profiles p
        where p.id = p_user_id
          and p.approved = true
          and p.disabled = false
          and (
            p.role = 'admin'
            or public.has_current_week_contribution(p_user_id, p_week_start)
          )
    );
$$;

alter table public.profiles enable row level security;
alter table public.photo_ingest_batches enable row level security;
alter table public.photo_candidates enable row level security;

drop policy if exists "profiles_self_select" on public.profiles;
create policy "profiles_self_select"
on public.profiles for select
to authenticated
using (id = auth.uid() or public.is_profile_admin(auth.uid()));

drop policy if exists "profiles_admin_update" on public.profiles;
create policy "profiles_admin_update"
on public.profiles for update
to authenticated
using (public.is_profile_admin(auth.uid()))
with check (public.is_profile_admin(auth.uid()));

drop policy if exists "profiles_admin_insert" on public.profiles;
create policy "profiles_admin_insert"
on public.profiles for insert
to authenticated
with check (public.is_profile_admin(auth.uid()));

drop policy if exists "batches_member_insert_own" on public.photo_ingest_batches;
create policy "batches_member_insert_own"
on public.photo_ingest_batches for insert
to authenticated
with check (
    user_id = auth.uid()
    and exists (
        select 1 from public.profiles p
        where p.id = auth.uid()
          and p.approved = true
          and p.disabled = false
    )
);

drop policy if exists "batches_member_select_own_or_admin" on public.photo_ingest_batches;
create policy "batches_member_select_own_or_admin"
on public.photo_ingest_batches for select
to authenticated
using (user_id = auth.uid() or public.is_profile_admin(auth.uid()));

drop policy if exists "batches_member_update_own_processing" on public.photo_ingest_batches;
create policy "batches_member_update_own_processing"
on public.photo_ingest_batches for update
to authenticated
using (user_id = auth.uid() or public.is_profile_admin(auth.uid()))
with check (user_id = auth.uid() or public.is_profile_admin(auth.uid()));

drop policy if exists "candidates_member_insert_own" on public.photo_candidates;
create policy "candidates_member_insert_own"
on public.photo_candidates for insert
to authenticated
with check (user_id = auth.uid());

drop policy if exists "candidates_select_own_or_admin" on public.photo_candidates;
create policy "candidates_select_own_or_admin"
on public.photo_candidates for select
to authenticated
using (user_id = auth.uid() or public.is_profile_admin(auth.uid()));

drop policy if exists "candidates_admin_update" on public.photo_candidates;
create policy "candidates_admin_update"
on public.photo_candidates for update
to authenticated
using (public.is_profile_admin(auth.uid()))
with check (public.is_profile_admin(auth.uid()));

drop policy if exists "photo_candidate_storage_insert" on storage.objects;
create policy "photo_candidate_storage_insert"
on storage.objects for insert
to authenticated
with check (
    bucket_id = 'photo-pool'
    and (storage.foldername(name))[1] = 'candidates'
    and (storage.foldername(name))[2] = auth.uid()::text
    and public.can_submit_weekly_video(auth.uid())
);

drop policy if exists "photo_candidate_storage_select" on storage.objects;
create policy "photo_candidate_storage_select"
on storage.objects for select
to authenticated
using (
    bucket_id = 'photo-pool'
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
using (bucket_id = 'photo-pool' and public.is_profile_admin(auth.uid()))
with check (bucket_id = 'photo-pool' and public.is_profile_admin(auth.uid()));

do $$
begin
    if to_regclass('public.photos') is not null then
        execute 'alter table public.photos enable row level security';
        execute 'drop policy if exists "photos_active_member_select" on public.photos';
        execute 'create policy "photos_active_member_select" on public.photos for select to authenticated using (public.is_active_member(auth.uid()))';
        execute 'drop policy if exists "photos_active_member_update" on public.photos';
        execute 'create policy "photos_active_member_update" on public.photos for update to authenticated using (public.is_active_member(auth.uid()) or public.is_profile_admin(auth.uid())) with check (public.is_active_member(auth.uid()) or public.is_profile_admin(auth.uid()))';
        execute 'drop policy if exists "photos_admin_insert" on public.photos';
        execute 'create policy "photos_admin_insert" on public.photos for insert to authenticated with check (public.is_profile_admin(auth.uid()))';
    end if;

    if to_regclass('public.process_logs') is not null then
        execute 'alter table public.process_logs enable row level security';
        execute 'drop policy if exists "process_logs_active_member_insert" on public.process_logs';
        execute 'create policy "process_logs_active_member_insert" on public.process_logs for insert to authenticated with check (public.is_active_member(auth.uid()))';
        execute 'drop policy if exists "process_logs_active_member_update" on public.process_logs';
        execute 'create policy "process_logs_active_member_update" on public.process_logs for update to authenticated using (public.is_active_member(auth.uid())) with check (public.is_active_member(auth.uid()))';
        execute 'drop policy if exists "process_logs_admin_select" on public.process_logs';
        execute 'create policy "process_logs_admin_select" on public.process_logs for select to authenticated using (public.is_profile_admin(auth.uid()))';
    end if;
end
$$;
