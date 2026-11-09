-- Suscripciones a los avisos por Telegram y correo. Solo se guarda lo imprescindible para enviarlos:
-- el chat de Telegram o el correo, los criterios y la cola de mensajes pendientes.

CREATE TABLE suscriptores (
  id INTEGER PRIMARY KEY,
  canal TEXT NOT NULL CHECK (canal IN ('telegram', 'correo')),
  destino TEXT NOT NULL,                 -- chat_id de Telegram o dirección de correo
  estado TEXT NOT NULL DEFAULT 'activo' CHECK (estado IN ('pendiente', 'activo')),
  token TEXT NOT NULL UNIQUE,            -- enlace de baja (correo)
  borrador TEXT,                         -- aviso a medias (bot) o pendiente de confirmar (correo), JSON
  creado TEXT NOT NULL,
  UNIQUE (canal, destino)
);

CREATE TABLE avisos (
  id INTEGER PRIMARY KEY,
  suscriptor INTEGER NOT NULL REFERENCES suscriptores (id) ON DELETE CASCADE,
  criterios TEXT NOT NULL,               -- JSON: ver src/criterios.js
  creado TEXT NOT NULL
);
CREATE INDEX avisos_suscriptor ON avisos (suscriptor);

-- Novedades ya vistas (api/novedades.json): cada una se avisa una sola vez.
CREATE TABLE novedades (
  id TEXT PRIMARY KEY,
  fecha TEXT NOT NULL,
  datos TEXT NOT NULL
);
CREATE INDEX novedades_fecha ON novedades (fecha);

-- Bandeja de salida: el plan gratuito permite pocas llamadas por ejecución, así que los mensajes
-- se envían por tandas desde el cron.
CREATE TABLE envios (
  id INTEGER PRIMARY KEY,
  suscriptor INTEGER NOT NULL REFERENCES suscriptores (id) ON DELETE CASCADE,
  asunto TEXT,                           -- solo correo
  texto TEXT NOT NULL,
  intentos INTEGER NOT NULL DEFAULT 0,
  despues TEXT NOT NULL                  -- no enviar antes (reintentos y límites de Telegram)
);
CREATE INDEX envios_despues ON envios (despues);

CREATE TABLE estado (
  clave TEXT PRIMARY KEY,
  valor TEXT NOT NULL
);
