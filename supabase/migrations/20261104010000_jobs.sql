-- Trabajos en segundo plano (generación de CVs): la petición solo encola; un worker (otra
-- invocación de la función) lo ejecuta, y el frontend consulta el estado y avisa al terminar.

create table if not exists jobs (
    id bigint generated always as identity primary key,
    user_id bigint not null references usuarios(id) on delete cascade,
    postulacion_id bigint not null references web_postulaciones(id) on delete cascade,
    tipo text not null default 'generar',
    estado text not null default 'pendiente',  -- pendiente | ejecutando | listo | error
    etapa text,                                 -- texto de progreso para la UI
    params jsonb not null default '{}'::jsonb,  -- ej. {"feedback": "..."}
    error text,
    intentos integer not null default 0,
    visto boolean not null default false,       -- el usuario ya fue notificado del resultado
    creado_en timestamptz not null default now(),
    iniciado_en timestamptz,
    latido_en timestamptz,                      -- pulso del worker: si se apaga, el job se reintenta
    terminado_en timestamptz
);
create index if not exists jobs_user_idx on jobs (user_id, id desc);
create index if not exists jobs_postulacion_idx on jobs (postulacion_id);
-- A lo más un job activo por postulación (evita doble clic / doble costo de IA).
create unique index if not exists jobs_activo_uq on jobs (postulacion_id) where estado in ('pendiente', 'ejecutando');

alter table jobs enable row level security;
