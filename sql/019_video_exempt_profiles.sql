alter table public.profiles
add column if not exists video_exempt boolean not null default false;

comment on column public.profiles.video_exempt is
'Permite que un usuario aprobado use la app sin video requerido, sin convertirlo en admin.';

drop policy if exists "batches_admin_insert_for_user" on public.photo_ingest_batches;
create policy "batches_admin_insert_for_user"
on public.photo_ingest_batches for insert
to authenticated
with check (public.is_profile_admin(auth.uid()));

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
    with policy as (
        select enabled
        from public.get_video_requirement_policy()
    )
    select exists (
        select 1
        from public.profiles p, policy v
        where p.id = p_user_id
          and p.approved = true
          and p.disabled = false
          and (
            p.role = 'admin'
            or p.video_exempt = true
            or v.enabled = false
            or public.has_current_week_contribution(p_user_id, p_week_start)
          )
    );
$$;
