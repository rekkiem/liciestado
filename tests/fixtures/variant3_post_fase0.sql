-- Variant 3: post Fase 0 (tipo_entidad, is_admin, api_quota limite/creado_en)
PRAGMA foreign_keys=OFF;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  nombre VARCHAR(120),
  plan VARCHAR(30) DEFAULT 'free',
  activo BOOLEAN DEFAULT 1,
  is_admin BOOLEAN DEFAULT 0,
  fecha_registro DATETIME,
  ultimo_acceso DATETIME
);

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
  user_id INTEGER,
  nombre VARCHAR(120) NOT NULL,
  criterios JSON NOT NULL,
  activa BOOLEAN NOT NULL DEFAULT 1,
  fecha_creacion DATETIME
);

CREATE TABLE IF NOT EXISTS alertas_generadas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  regla_id INTEGER,
  licitacion_codigo VARCHAR(60),
  tipo_entidad VARCHAR(30),
  mensaje TEXT,
  leida BOOLEAN DEFAULT 0,
  fecha DATETIME
);

CREATE TABLE IF NOT EXISTS api_quota_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  fecha VARCHAR(10) NOT NULL,
  requests INTEGER DEFAULT 0,
  limite INTEGER DEFAULT 10000,
  creado_en DATETIME,
  UNIQUE(user_id, fecha)
);

INSERT INTO users (email, password_hash, nombre, plan, activo, is_admin, fecha_registro)
VALUES ('admin@test.cl', 'hash', 'Admin', 'pro', 1, 1, '2026-01-01');

INSERT INTO licitaciones_snapshot (codigo, tipo, datos, region, monto_clp, estado, fecha_publicacion, fecha_sincronizacion)
VALUES
 ('L1-V3', 'licitacion', '{"organismo":"Ministerio X","categoria":"TI","tipo":"L1"}', 'Metropolitana', 1000000, 'Publicada', '2026-01-15', '2026-01-16'),
 ('L2-V3', 'licitacion', '{"organismo":"Ministerio X","categoria":"TI"}', 'Metropolitana', 500000, 'Publicada', '2026-01-20', '2026-01-21'),
 ('L3-V3', 'licitacion', '{"organismo":"Seremi Y","categoria":"Obras"}', 'Valparaíso', 2500000, 'Publicada', '2026-02-01', '2026-02-02');

INSERT INTO reglas_usuario (user_id, nombre, criterios, activa) VALUES (1, 'Regla V3', '{"keywords":["software"]}', 1);
INSERT INTO alertas_generadas (user_id, regla_id, licitacion_codigo, tipo_entidad, mensaje, leida, fecha)
VALUES (1, 1, 'L1-V3', 'licitacion', 'Match', 0, '2026-01-16');
INSERT INTO api_quota_logs (user_id, fecha, requests, limite, creado_en)
VALUES (1, '2026-01-16', 10, 10000, '2026-01-16');
