-- Novedades con orden de llegada propio y reparto pendiente (aún sin suscriptores: se recrea vacía).
-- n: AUTOINCREMENT no reutiliza números al borrar las antiguas, así el cursor del correo no se salta ninguna.
-- pendiente: se guarda la novedad marcada y la marca se quita al encolar sus mensajes; si el reparto
-- falla, la recepción siguiente lo reintenta en vez de darla por avisada.
DROP TABLE novedades;
CREATE TABLE novedades (
  n INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  fecha TEXT NOT NULL,
  datos TEXT NOT NULL,
  pendiente INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX novedades_fecha ON novedades (fecha);
CREATE INDEX novedades_pendientes ON novedades (n) WHERE pendiente = 1;
DELETE FROM estado WHERE clave = 'correo_desde';
