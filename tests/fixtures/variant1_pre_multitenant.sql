-- Variant 1: pre multi-tenant (sin user_id en reglas/alertas)
-- SQLite schema mínimo + 2 filas de snapshot
PRAGMA foreign_keys=OFF;

CREATE TABLE IF NOT EXISTS licitaciones_snapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  codigo VARCHAR(60) NOT NULL UNIQUE,
  tipo VARCHAR(30) NOT NULL DEFAULT 'licitacion',
  datos JSON NOT NULL,
  region VARCHAR(80),
  monto_clp INTEGER,
  estado VARCHAR(60),
  fecha_publicacion DATETIME,
  fecha_sincronizacion DATETIME
);

CREATE TABLE IF NOT EXISTS reglas_usuario (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre VARCHAR(120) NOT NULL,
  criterios JSON NOT NULL,
  activa BOOLEAN NOT NULL DEFAULT 1,
  fecha_creacion DATETIME
);

CREATE TABLE IF NOT EXISTS alertas_generadas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  regla_id INTEGER,
  licitacion_codigo VARCHAR(60),
  mensaje TEXT,
  leida BOOLEAN DEFAULT 0,
  fecha DATETIME
);

INSERT INTO licitaciones_snapshot (codigo, tipo, datos, region, monto_clp, estado, fecha_publicacion, fecha_sincronizacion)
VALUES
 ('L1-V1', 'licitacion', '{"organismo":"Ministerio X","categoria":"TI"}', 'Metropolitana', 1000000, 'Publicada', '2026-01-15', '2026-01-16'),
 ('L2-V1', 'licitacion', '{"organismo":"Seremi Y","categoria":"Obras"}', 'Valparaíso', 2500000, 'Publicada', '2026-02-01', '2026-02-02');

INSERT INTO reglas_usuario (nombre, criterios, activa) VALUES ('Regla legacy', '{"keywords":["software"]}', 1);
