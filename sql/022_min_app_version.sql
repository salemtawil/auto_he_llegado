-- Piso de version: obligar a reinstalar la app.
--
-- Problema que resuelve: la exigencia del video se decide en Python, asi que
-- una instalacion que no trae ese codigo sencillamente no se la pregunta. No
-- hay forma de arreglar eso desde el cliente -esa app ya esta instalada y no
-- sabe comprobar nada-. La unica palanca es que el servidor deje de servirle.
--
-- Como: la app al dia se identifica con la cabecera `x-app-version` en cada
-- peticion. La app vieja no la manda. Las politicas rechazan a quien llegue
-- sin cabecera o por debajo del minimo.
--
-- SE INSTALA APAGADO. `enabled` en false no cierra nada. Encenderlo y apagarlo
-- es cambiar una fila, sin reconstruir ni repartir nada.
--
-- ANTES DE ENCENDERLO: que el instalador nuevo este repartido y que los
-- agentes esten avisados. La app vieja va a fallar en el login con un error
-- generico, y no se puede hacer que muestre un mensaje bonito: esa version
-- enmascara los errores del servidor antes de enseñarlos.

-- 1. El ajuste. Apagado, y con la version a la que se va a exigir llegar.
insert into public.app_settings (key, value)
values (
    'min_app_version',
    '{"enabled": false, "version": "2026.11.16.1", "mensaje": ""}'::jsonb
)
on conflict (key) do nothing;


-- 2. Que version dice ser quien esta llamando.
--    Null si no lo dice: eso es, exactamente, una app vieja.
create or replace function public.app_version_de_la_peticion()
returns text
language sql
stable
as $$
    select nullif(
        trim(coalesce(
            current_setting('request.headers', true)::json ->> 'x-app-version',
            ''
        )),
        ''
    );
$$;

grant execute on function public.app_version_de_la_peticion() to anon, authenticated;


-- 3. El minimo, legible por cualquiera que haya entrado.
--    `app_settings` solo lo leen los admins, y la app necesita este dato para
--    poder explicarle al agente por que no entra.
create or replace function public.get_min_app_version()
returns table(enabled boolean, version text, mensaje text)
language sql
stable
security definer
set search_path = public
as $$
    select
        coalesce((s.value->>'enabled')::boolean, false) as enabled,
        coalesce(nullif(trim(s.value->>'version'), ''), '') as version,
        coalesce(nullif(trim(s.value->>'mensaje'), ''), '') as mensaje
    from public.app_settings s
    where s.key = 'min_app_version'
    union all
    select false, '', ''
    where not exists (
        select 1 from public.app_settings s where s.key = 'min_app_version'
    )
    limit 1;
$$;

grant execute on function public.get_min_app_version() to anon, authenticated;


-- 4. Comparar dos versiones del tipo AAAA.MM.DD.N.
--    Se rellena con ceros, asi "2026.11.16" y "2026.11.16.0" son la misma.
--    Una version ilegible devuelve null, y null nunca cuenta como suficiente.
create or replace function public.partes_de_version(p_version text)
returns int[]
language plpgsql
immutable
as $$
declare
    v_texto text := trim(coalesce(p_version, ''));
begin
    if v_texto = '' or v_texto !~ '^[0-9]+(\.[0-9]+)*$' then
        return null;
    end if;
    return string_to_array(v_texto, '.')::int[];
end;
$$;

grant execute on function public.partes_de_version(text) to anon, authenticated;


-- 5. La regla. True = puede pasar.
create or replace function public.app_version_permitida()
returns boolean
language plpgsql
stable
security definer
set search_path = public
as $$
declare
    v_ajuste record;
    v_minima int[];
    v_tengo int[];
    v_largo int;
begin
    select * into v_ajuste from public.get_min_app_version();

    -- Apagado: no se exige nada.
    if v_ajuste is null or not v_ajuste.enabled then
        return true;
    end if;

    -- Minimo mal escrito: no se exige nada. Un dedazo en la tabla de ajustes
    -- no puede dejar a toda la empresa fuera.
    v_minima := public.partes_de_version(v_ajuste.version);
    if v_minima is null then
        return true;
    end if;

    -- Los admins entran siempre. Es la salida de emergencia: si esto se
    -- enciende mal, tiene que quedar alguien que pueda volver a apagarlo.
    if public.is_profile_admin(auth.uid()) then
        return true;
    end if;

    v_tengo := public.partes_de_version(public.app_version_de_la_peticion());
    if v_tengo is null then
        return false;
    end if;

    v_largo := greatest(array_length(v_tengo, 1), array_length(v_minima, 1));
    for i in 1..v_largo loop
        if coalesce(v_tengo[i], 0) > coalesce(v_minima[i], 0) then
            return true;
        elsif coalesce(v_tengo[i], 0) < coalesce(v_minima[i], 0) then
            return false;
        end if;
    end loop;
    return true;
end;
$$;

grant execute on function public.app_version_permitida() to anon, authenticated;


-- 6. El candado, en la lectura del perfil.
--    Es lo primero que hace la app despues del login, asi que la app vieja
--    falla en la pantalla de entrada y no a media corrida, cuando el agente
--    ya habria hecho el trabajo.
--
--    Se reescribe la politica de 006 entera, añadiendole la condicion. Los
--    admins conservan su acceso completo, por lo dicho arriba.
drop policy if exists "profiles_self_select" on public.profiles;
create policy "profiles_self_select"
on public.profiles for select
to authenticated
using (
    public.is_profile_admin(auth.uid())
    or (id = auth.uid() and public.app_version_permitida())
);

notify pgrst, 'reload schema';


-- COMO ENCENDERLO (cuando el instalador este repartido y la gente avisada):
--
--   update public.app_settings
--   set value = jsonb_set(value, '{enabled}', 'true'::jsonb),
--       updated_at = timezone('utc', now())
--   where key = 'min_app_version';
--
-- COMO APAGARLO (vuelve todo a la normalidad en segundos):
--
--   update public.app_settings
--   set value = jsonb_set(value, '{enabled}', 'false'::jsonb),
--       updated_at = timezone('utc', now())
--   where key = 'min_app_version';
--
-- COMO SUBIR EL MINIMO MAS ADELANTE:
--
--   update public.app_settings
--   set value = jsonb_set(value, '{version}', '"2027.01.15.1"'::jsonb),
--       updated_at = timezone('utc', now())
--   where key = 'min_app_version';
--
-- COMPROBAR SIN ENCENDERLO: con la funcion instalada y el ajuste apagado,
-- esto dice que version esta mandando la app que tengas delante.
--
--   select public.app_version_de_la_peticion();
