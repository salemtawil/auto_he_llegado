-- 020_multi_photo_pool_buckets.sql
--
-- Objetivo
-- --------
-- Que un administrador elija explicitamente, por lote, a que bucket de fotos
-- sube los archivos, sin cambiar el pool activo del que consumen las corridas.
--
-- Modelo
-- ------
-- * "Pool activo" = app_settings['photo_pool'].bucket (get_photo_pool_policy).
--   Es el unico del que las corridas reclaman fotos. No cambia aqui.
-- * "Destinos de carga" = los buckets que existen DE VERDAD en storage.buckets,
--   menos los excluidos explicitamente. La lista NO esta escrita a mano en
--   ningun sitio: sale del inventario real de Storage cada vez que se consulta.
-- * "Excluidos" = app_settings['photo_pool_excluded_buckets'].buckets
--   Buckets que existen pero no deben recibir cargas nuevas (legacy).
--
-- El pool activo NO limita los destinos: un administrador puede subir a
-- cualquier bucket apto aunque no sea el activo. Las fotos subidas a un bucket
-- no activo quedan ahi y las corridas no las consumen, porque
-- claim_available_photo() sigue filtrando por el bucket activo (sin cambios).
--
-- IMPORTANTE: aplicar primero en un entorno de prueba.

-- ---------------------------------------------------------------------------
-- 1. Buckets excluidos como destino de carga
-- ---------------------------------------------------------------------------
--
-- Se siembra con 'photos', el bucket legacy. Para no excluir nada, sustituye
-- el literal por '{"buckets": []}'::jsonb antes de aplicar.

insert into public.app_settings (key, value)
values (
    'photo_pool_excluded_buckets',
    '{"buckets": ["photos"]}'::jsonb
)
on conflict (key) do nothing;

-- Lee la lista de exclusiones con validacion defensiva de la forma del JSON.
--
-- El guard va DENTRO del argumento de jsonb_array_elements, no en un WHERE:
-- Postgres no garantiza evaluar el filtro antes de la funcion en un LATERAL,
-- asi que un valor que no sea array (un escalar, un objeto, null) haria
-- reventar la funcion con "cannot extract elements from a scalar". Con el CASE,
-- un valor invalido produce un array vacio y la consulta termina bien: se
-- ignora la exclusion en vez de romper cualquier operacion de Storage.
create or replace function public.excluded_photo_pool_buckets()
returns table(bucket text)
language sql
stable
security definer
set search_path = public
as $$
    select distinct btrim(elem #>> '{}') as bucket
    from public.app_settings s
    cross join lateral jsonb_array_elements(
        case
            when jsonb_typeof(s.value) = 'object'
             and jsonb_typeof(s.value -> 'buckets') = 'array'
            then s.value -> 'buckets'
            else '[]'::jsonb
        end
    ) as elem
    where s.key = 'photo_pool_excluded_buckets'
      and jsonb_typeof(elem) = 'string'
      and btrim(elem #>> '{}') <> '';
$$;

revoke all on function public.excluded_photo_pool_buckets() from public;
grant execute on function public.excluded_photo_pool_buckets() to authenticated;

-- ---------------------------------------------------------------------------
-- 2. Destinos de carga = inventario real de Storage menos exclusiones
-- ---------------------------------------------------------------------------
--
-- Devuelve TODOS los buckets que existen, marcando cuales son aptos. La app
-- muestra los no aptos en gris con su motivo, en vez de esconderlos: asi el
-- administrador ve que el bucket existe y por que no puede usarlo.
create or replace function public.photo_pool_upload_targets()
returns table(
    bucket text,
    is_active boolean,
    is_eligible boolean,
    reason text
)
language sql
stable
security definer
set search_path = public, storage
as $$
    select
        b.id::text as bucket,
        b.id::text = public.active_photo_pool_bucket() as is_active,
        not exists (
            select 1
            from public.excluded_photo_pool_buckets() e
            where e.bucket = b.id::text
        ) as is_eligible,
        case
            when exists (
                select 1
                from public.excluded_photo_pool_buckets() e
                where e.bucket = b.id::text
            )
            then 'Excluido como destino de carga (legacy).'
            else null
        end as reason
    from storage.buckets b
    where public.is_profile_admin(auth.uid())
    order by b.id::text;
$$;

revoke all on function public.photo_pool_upload_targets() from public;
grant execute on function public.photo_pool_upload_targets() to authenticated;

-- Predicado usado por las politicas de Storage y por la app antes de subir.
create or replace function public.is_allowed_photo_pool_bucket(p_bucket text)
returns boolean
language sql
stable
security definer
set search_path = public, storage
as $$
    select exists (
        select 1
        from storage.buckets b
        where b.id::text = btrim(coalesce(p_bucket, ''))
    )
    and not exists (
        select 1
        from public.excluded_photo_pool_buckets() e
        where e.bucket = btrim(coalesce(p_bucket, ''))
    );
$$;

revoke all on function public.is_allowed_photo_pool_bucket(text) from public;
grant execute on function public.is_allowed_photo_pool_bucket(text) to authenticated;

-- ---------------------------------------------------------------------------
-- 3. Politicas de Storage: extension MINIMA para administradores
-- ---------------------------------------------------------------------------
--
-- La politica existente "photo_admin_storage_write" (FOR ALL sobre el bucket
-- ACTIVO) se conserva intacta: los flujos actuales de revision, mantenimiento
-- y limpieza (que usan move, o sea UPDATE) siguen funcionando igual y siguen
-- limitados al pool activo.
--
-- Lo que se agrega son tres politicas de UNA sola operacion cada una, que
-- cubren solo lo que la carga a un bucket NO activo necesita. No se concede
-- UPDATE a proposito: subir es un INSERT (upload_binary usa upsert=false), de
-- modo que un administrador no puede sobrescribir objetos existentes en un
-- bucket que no es el activo.
--
--   INSERT -> subir el archivo (uploader_service._upload_binary_with_retries)
--   SELECT -> leer/verificar el objeto recien subido
--   DELETE -> revertirlo cuando falla el insert en la tabla photos
--             (uploader_service._rollback_storage_file)
--
-- Las politicas de usuarios NO administradores
-- ("photo_candidate_storage_insert" y "photo_candidate_storage_select") no se
-- tocan y siguen ligadas al bucket activo.

drop policy if exists "photo_admin_pool_upload_insert" on storage.objects;
create policy "photo_admin_pool_upload_insert"
on storage.objects for insert
to authenticated
with check (
    public.is_allowed_photo_pool_bucket(bucket_id)
    and public.is_profile_admin(auth.uid())
);

drop policy if exists "photo_admin_pool_upload_select" on storage.objects;
create policy "photo_admin_pool_upload_select"
on storage.objects for select
to authenticated
using (
    public.is_allowed_photo_pool_bucket(bucket_id)
    and public.is_profile_admin(auth.uid())
);

drop policy if exists "photo_admin_pool_upload_delete" on storage.objects;
create policy "photo_admin_pool_upload_delete"
on storage.objects for delete
to authenticated
using (
    public.is_allowed_photo_pool_bucket(bucket_id)
    and public.is_profile_admin(auth.uid())
);

-- ---------------------------------------------------------------------------
-- 4. Revision de privilegios SECURITY DEFINER preexistentes
-- ---------------------------------------------------------------------------
--
-- list_photo_pool_buckets() devuelve todo el inventario de storage.buckets y
-- hoy lo puede ejecutar cualquier usuario autenticado. Se le agrega el filtro
-- de administrador para no revelar el inventario a usuarios normales. La firma
-- no cambia, asi que el panel "Pool activo" sigue funcionando igual.
create or replace function public.list_photo_pool_buckets()
returns table(bucket text)
language sql
stable
security definer
set search_path = public, storage
as $$
    select b.id::text as bucket
    from storage.buckets b
    where public.is_profile_admin(auth.uid())
    order by b.id::text;
$$;

revoke all on function public.list_photo_pool_buckets() from public;
grant execute on function public.list_photo_pool_buckets() to authenticated;

-- get_photo_pool_policy() y active_photo_pool_bucket() siguen concedidas a
-- anon porque las politicas de candidatos no administradores las evaluan; solo
-- exponen el nombre del bucket activo. No se amplian.

notify pgrst, 'reload schema';
