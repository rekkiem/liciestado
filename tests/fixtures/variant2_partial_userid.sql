-- Variant 2: user_id parcial (columna existe, algunas filas NULL)
PRAGMA foreign_keys=OFF;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  nombre VARCHAR(120),
  plan VARCHAR(30) DEFAULT 'free',
  activo BOOLEAN DEFAULT 1,
  fecha_registro DATETIME
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
  mensaje TEXT,
  leida BOOLEAN DEFAULT 0,
  fecha DATETIME
);

INSERT INTO users (email, password_hash, nombre, plan, activo, fecha_registro)
VALUES ('user@test.cl', 'hash', 'User', 'free', 1, '2026-01-01');

INSERT INTO licitaciones_snapshot (codigo, tipo, datos, region, monto_clp, estado, fecha_publicacion, fecha_sincronizacion)
VALUES
 ('L1-V2', 'licitacion', '{"organismo":"Ministerio X","categoria":"TI"}', 'Metropolitana', 1000000, 'Publicada', '2026-01-15', '2026-01-16');

INSERT INTO reglas_usuario (user_id, nombre, criterios, activa) VALUES (1, 'Con user', '{"keywords":["red"]}', 1);
INSERT INTO reglas_usuario (user_id, nombre, criterios, activa) VALUES (NULL, 'Sin user', '{"keywords":["obra"]}', 1);
