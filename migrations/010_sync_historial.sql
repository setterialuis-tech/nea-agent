-- 010_sync_historial.sql — Nea completa su memoria con lo que el CRM envió o
-- recibió sin ella (campañas, plantillas, chat humano, entrantes con la IA
-- apagada). Idempotente.
--
-- crm_sync_cursor: «<createdAt ISO ms>|<id>» del último mensaje del CRM ya
-- visto en esta conversación. NULL = aún no se ha sincronizado.
-- source: de dónde salió la fila (NULL = la escribió Nea misma).

ALTER TABLE bot_conversation ADD COLUMN IF NOT EXISTS crm_sync_cursor TEXT;
ALTER TABLE bot_message ADD COLUMN IF NOT EXISTS source TEXT;
