-- Borrado de usuarios desde el panel de administracion.
--
-- Hoy `profiles` y `photo_ingest_batches` no tienen ninguna politica de
-- DELETE, asi que con RLS activa un borrado afecta a cero filas y PostgREST
-- no devuelve error: la app creeria que borro y no borro nada.
--
-- Solo administradores. No toca `auth.users`: esa cuenta solo la puede borrar
-- la clave de servicio, y sin perfil el login ya queda bloqueado.

drop policy if exists profiles_admin_delete on public.profiles;
create policy profiles_admin_delete
on public.profiles for delete
to authenticated
using (
    public.is_profile_admin(auth.uid())
    -- Un admin no puede borrarse a si mismo: dejaria el proyecto sin quien
    -- administre si es el unico.
    and id <> auth.uid()
);

drop policy if exists batches_admin_delete on public.photo_ingest_batches;
create policy batches_admin_delete
on public.photo_ingest_batches for delete
to authenticated
using (public.is_profile_admin(auth.uid()));
