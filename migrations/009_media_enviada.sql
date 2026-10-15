-- 009_media_enviada.sql — imágenes/videos que Nea ya envió en cada conversación.
-- La herramienta send_media manda cada recurso UNA sola vez por conversación;
-- esta tabla es la memoria de eso. /reset la vacía. Idempotente.

CREATE TABLE IF NOT EXISTS media_enviada (
  conversation_id BIGINT NOT NULL REFERENCES bot_conversation (id) ON DELETE CASCADE,
  url             TEXT   NOT NULL,
  sent_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (conversation_id, url)
);
