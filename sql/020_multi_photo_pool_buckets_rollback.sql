-- Reversion de 020_multi_photo_pool_buckets.sql
--
-- Deja un solo destino de carga (el pool activo), que es el comportamiento de
-- 019_remote_photo_pool_policy.sql. No borra fotos ni objetos de Storage: las
-- ya subidas a otros buckets permanecen donde estan.

drop policy if exists "photo_admin_pool_upload_insert" on storage.objects;
drop policy if exists "photo_admin_pool_upload_select" on storage.objects;
drop policy if exists "photo_admin_pool_upload_delete" on storage.objects;

drop function if exists public.is_allowed_photo_pool_bucket(text);
drop function if exists public.photo_pool_upload_targets();
drop function if exists public.excluded_photo_pool_buckets();

-- Restaura list_photo_pool_buckets() sin el filtro de administrador.
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

delete from public.app_settings where key = 'photo_pool_excluded_buckets';

notify pgrst, 'reload schema';
