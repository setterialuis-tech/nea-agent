# Cambios

Qué cambia en cada versión de Nea y qué hacer al actualizar. Cada tag
`vX.Y.Z` publica la imagen `ghcr.io/kevinrivm/nea-agent:X.Y.Z` (README,
«Instalar»).

## 1.12.1 — 2026-10-23

- **Une dos líneas que se publicaron en paralelo.** `v1.11.4` (el país del número, desde la rama `release/1.11.4`, ya desplegada en Roger) no traía el modo ahorro, y `v1.12.0` (modo ahorro, 1.11.1–1.11.3 y el origen de anuncio en todos los turnos) no traía el país del número. Esta versión trae todo: 1.11.4 + 1.12.0. Sin cambios de código respecto a la punta de la rama. Desplegar `1.12.0` o `1.11.4` por separado hace perder lo del otro.

### Actualizar desde 1.11.4

Con el CRM en 1.26.0 o más. Sin variables nuevas; el modo ahorro queda apagado hasta que se encienda en Agente → Mensajes.

## 1.11.4 — 2026-10-23

- **El agente sabe de qué país es el número de quien le escribe.** Antes el modelo no veía el teléfono del lead y trataba como local a quien escribía desde otro país (en producción, pacientes dominicanos atendidos como colombianos). Ahora el contexto trae «PAÍS DEL NÚMERO: su teléfono (+…) es de X» —calculado con el prefijo, con la librería `phonenumbers==9.0.41` (dependencia nueva)—, o «desconocido» si WhatsApp no compartió el número. Es una pista, no un dato seguro, y no asume cuál es el país del negocio: qué hacer con ella lo dice el prompt del negocio. Al actualizar: redesplegar (la imagen instala la dependencia).

## 1.11.3 — 2026-10-22

- **Si el CRM no tiene el teléfono del lead, el agente lo pide.** WhatsApp no manda el número de quien usa nombre de usuario (contacto `bsuid:`); el CRM lo entrega como `contact.phone: null`. Ahora el contexto del agente trae «TELÉFONO FALTANTE» (solo en WhatsApp y solo si el CRM manda el campo) para que pida el número una vez antes de pasar al lead al equipo, y `Transmitir_aviso` acepta `telefono` opcional que se reenvía a `POST /api/bot/qualify` (el CRM 1.25.3 lo usa solo si el contacto no tiene teléfono). Sin el campo, todo queda como antes. Al actualizar: redesplegar; el texto que hace que el agente lo pida va en el prompt del negocio.

## 1.12.0 — 2026-10-23

- **Modo ahorro para leads sin ventana gratis** (Agente → Mensajes del CRM 1.26.0; apagado por defecto). Con él encendido, un lead que no tiene ventana gratis (orgánico, o de anuncio pasadas las 72 h de la conversación) recibe lo mínimo de mensajes: tope propio `saverMaxParts` (por defecto 1; la respuesta con una imagen sale en 2: el texto y la imagen con el resto en su pie) y el formateador recibe al final de su prompt «# CONTEXTO DE ESTA RESPUESTA: este lead NO tiene ventana gratis…», que la sección «MODO AHORRO» del prompt de fábrica (editable en el CRM) sabe interpretar. Apagado, nada cambia: el formateador no se entera.
- **El origen de anuncio ya vale en todos los turnos.** Antes solo se detectaba en el primer mensaje (el que trae el `referral`); desde el segundo, un lead de anuncio contaba como orgánico y usaba el tope de orgánicos. Ahora se lee `conversation.origin` / `conversation.freeWindow` del contexto del CRM (1.26.0). Con un CRM anterior se sigue usando el `referral`.

### Actualizar desde 1.11.2

Actualiza primero el CRM a 1.26.0 (migración aditiva `0043`: dos columnas con valor por defecto). Con un CRM anterior, Nea 1.12.0 se comporta como 1.11.2.

## 1.11.2 — 2026-10-22

- **El formateador limpia también lo que va en un solo mensaje.** Con el tope por respuesta completa (1.11.1) un bloque de texto puede tocarle un solo mensaje, y entonces no se consultaba al modelo: quedaban el «¡», los asteriscos y la falta de emojis. Ahora se consulta a partir de 120 caracteres aunque el bloque sea de una sola parte (una llamada barata al modelo del formateador, sin costo de WhatsApp; el de n8n también limpiaba siempre).

## 1.11.1 — 2026-10-22

- **El tope de mensajes cuenta la respuesta completa, archivos incluidos.** Antes «Mensajes por respuesta» (Agente → Mensajes) se aplicaba a cada bloque de texto por separado: con una imagen en medio, un tope de 3 daba 5 mensajes (3 de texto + la imagen + el texto del enlace). Ahora cada imagen, video o PDF cuenta como un mensaje. Si no alcanza un mensaje por bloque, el texto que sigue a un archivo pasa a su **pie de foto** (los enlaces siguen siendo clicables), del último al primero y mientras quepa en 1024 caracteres; lo que sobra del presupuesto se reparte entre los bloques, más a los largos. Nunca se pierde texto: si no cabe, se pasa del tope antes que cortar. Caso del exterior: anuncio (3) = texto + imagen + texto; orgánico (2) = texto + imagen con el enlace en su pie. Cada mensaje de la API cuenta para el costo del cliente.

### Actualizar desde 1.11.0

Sin variables nuevas. Con el CRM 1.25.1 la pantalla «Probar» del formateador muestra el mismo reparto.

## 1.11.0 — 2026-10-22

- **El formateador vuelve a ser el de n8n.** El agente conversacional escribe UNA respuesta completa, con la URL de cada imagen, video o PDF dentro del texto (📸 / 🎥), y deja de depender de la herramienta `send_media`. Nea saca esos archivos **con código** (por extensión: `.jpg .jpeg .png .webp`, `.mp4 .mov .3gp`, `.pdf`; páginas, YouTube, mapas y WhatsApp se quedan como texto), reparte el texto con el formateador y envía todo **en el orden en que el agente lo escribió**: texto → archivo → texto. Módulo nuevo `app/multimedia.py` (espejo de `src/lib/formatear.ts` del CRM; comparten casos de prueba).
- **Pie de foto dinámico.** «Caption: …» en la línea siguiente al archivo es su pie; sin él, la frase que lo presenta (termina en «:» o «👇», p. ej. «Mira cómo se arma 👇») pasa a ser su pie, en vez de quedar un mensaje suelto.
- **Una vez por conversación, sin perder la URL.** Un archivo ya enviado no se repite (también si el modelo además llama `send_media`). Si el CRM no puede mandarlo (dominio no permitido, sin soporte), el paciente lo recibe como enlace.
- **Prompt del formateador editable desde el CRM** (Ajustes → IA → «Formatear la respuesta», CRM 1.25.0): `GET /api/bot/profile` trae `formatPrompt`; sin él, el de fábrica (basado en el «GPT formateador» de n8n). El formateador solo recibe la respuesta del agente (no el historial). Entiende el formato de n8n (`{"response": {"part_1"…"part_4"}}`) y el simple (`{"partes": [...]}`); máximo 4 partes. Su salida se valida igual que antes (enlaces, preguntas, viñetas, largo) y, si falla, se usan las reglas de código.
- La memoria guarda la respuesta con sus archivos (`📸 URL`), no solo el texto.

### Actualizar desde 1.10.1

Sin variables nuevas. Con un CRM anterior a 1.25.0 sigue funcionando con el prompt de fábrica. Para dejar de ofrecerle `send_media` al modelo pon `SEND_MEDIA_ENABLED=false` y quita del Prompt único las instrucciones de esa herramienta.

## 1.10.0 — 2026-10-21

- **Herramienta `Transmitir_aviso(reclamo, tipo)`.** Es la misma vía de `qualify_lead` (POST `/api/bot/qualify` del CRM) con el nombre y los parámetros que ya usa el prompt del negocio, y con `tipo` = `PRESENCIAL` | `RECLAMO` | `AVANZADO` para que el CRM avise por su webhook a n8n. Un `tipo` inventado se rechaza (el modelo reintenta) y nunca se avisa con él. Se enciende con `TRANSMITIR_AVISO_ENABLED=true` y **sustituye** a `qualify_lead` (no se ofrecen las dos). Requiere un CRM con el webhook de avisos (1.23.2+) y `AVISOS=on`; contra uno anterior el aviso se registra pero no sale por webhook.
- Sin cambios si no pones la variable.

### Actualizar desde 1.9.2

Pon `TRANSMITIR_AVISO_ENABLED=true` en la app de Nea y **redespliega** (una variable nueva solo se inyecta en un deploy).

## 1.9.1 — 2026-10-20

- **Nunca más un «.» o un emoji suelto.** Todo texto que escribe el modelo se descarta si, quitando espacios, signos, números y emojis, no quedan letras reales (seguimiento: mínimo 3; respuesta del turno: mínimo 2, así «Sí» pasa). El motivo queda en el log. El 21-oct el empujón mandó un «.» y un emoji a pacientes.
- **Seguimiento rápido configurable desde el CRM.** `GET /api/bot/profile` puede traer `followup` (`enabled`, `hours`, `prompt`). Apagado: Nea no programa ni envía empujones; el `prompt` reemplaza la instrucción fija; `hours` reemplaza `FOLLOWUP_HOURS`. Sin el dato (CRM anterior a 1.21.1) Nea se comporta como antes (`FOLLOWUP_HOURS` del entorno). Ventana de 24 h, IA pausada y handoff se respetan igual. Cambios en máx. 5 min (caché del perfil).

## 1.9.0 — 2026-10-20

- **Memoria completa.** Al empezar cada turno (y antes de un seguimiento) Nea pide al CRM los mensajes posteriores al último que ya vio (`GET /api/bot/messages`, por cursor) y los incorpora a su historial: campañas, plantillas, seguimientos, recordatorios, el chat de un humano y lo que el paciente escribió con la IA apagada. Lo de origen CRM entra con una marca (`[Plantilla enviada]`, `[Mensaje del equipo]`) que Nea nunca repite al lead. Sin duplicados (filas y cursor se escriben juntos). Migración `010` (columnas nuevas, idempotente). Necesita CRM 1.21.x; con un CRM anterior se degrada sin error (404 → sigue como antes).

## 1.8.0 — 2026-10-19

- **Modelo por función desde el CRM.** `GET /api/bot/profile` puede traer `models`
  (conversacion, formato, audio, vision), cada uno con proveedor, base, modelo y llave
  — se configuran en el CRM (Ajustes → IA, una tarjeta por función) y mandan sobre el
  entorno de Nea. Lo que el CRM no mande se queda como estaba (`LLM_MODEL`,
  `FORMAT_MODEL`, `LLM_TRANSCRIBE_MODEL`, `VISION_MODEL`). Los cambios llegan en un
  máximo de 5 minutos (la caché del perfil), sin redesplegar. Un modelo del CRM que no
  se pueda construir se registra (sin la llave) y se usa el del entorno. Las llaves
  viven solo en memoria. Necesita CRM 1.18.0.

## 1.7.0 — 2026-10-18

- La espera de agrupación de mensajes (`coalesceSeconds`) también viene de `messaging` en el perfil del CRM (Agente → Mensajes) y manda sobre `COALESCE_SECONDS`.

## 1.6.0 — 2026-10-18

### Nuevo

- **Vertex AI** como proveedor: `LLM_PROVIDER=vertex` + `LLM_VERTEX_CREDENTIALS`
  (JSON de la cuenta de servicio). El token se renueva solo. Modelo recomendado:
  `google/gemini-2.5-flash`.
- **Un modelo por función**: conversar, oír audios, ver imágenes (`VISION_MODEL`) y
  dar forma a la respuesta (`FORMAT_MODEL`), cada uno con su proveedor opcional.
- **Respuesta en varios mensajes**: se parte por párrafos y listas sin cortar una
  pregunta ni un enlace, hasta `MAX_PARTS_ADS` (lead de anuncio) o
  `MAX_PARTS_ORGANIC` mensajes, con pausa entre ellos. Con `FORMAT_MODEL`, un modelo
  reparte el texto (quita asteriscos decorativos, emojis, listas) y su salida se
  valida contra el original; si no cuadra, se usan las reglas de código.
- El CRM puede mandar `messaging` en `GET /api/bot/profile` (máximos de mensajes,
  espera, pausa y uso del formateador); manda sobre el entorno.

### Arreglado

- Una respuesta con caracteres de otro alfabeto, marcas internas del modelo o una
  herramienta escrita como texto (DeepSeek vía OpenRouter) ya no llega al lead: se
  pide otra respuesta y, si vuelve a fallar, silencio + handoff `error`.

## 1.0.0 — 2026-09-30

Primera versión con número y primera con imagen publicada. Hasta aquí Nea se
instalaba construyendo `main`. Lo de abajo cuenta desde el `main` del 18-sep
(`c90ec87`): los PR #27, #28, #29, #30 y #32. Si tu copia es más vieja, lee también
el final de «Actualizar».

> **¿Corres el modo estándar con un `main` de entre el 31-ago y el 21-sep?**
> Tu Nea no le está pasando los mensajes al CRM. Actualiza (ver «Actualizar»).

> **Modo estándar: `META_APP_SECRET` ahora es obligatoria.** Sin ella,
> `POST /webhook` responde 401 y Nea deja de recibir mensajes. Ponla antes de
> actualizar.

### Nuevo

- **Imagen en GHCR** (#29). Cada tag `vX.Y.Z` publica
  `ghcr.io/kevinrivm/nea-agent:X.Y.Z`, además de `X.Y` y `latest`, para
  `linux/amd64`. Coolify la descarga en vez de construirla en el VPS. El CI
  construye la imagen en cada PR y en cada push a `main`, sin publicarla.
- **`/health` dice qué Nea corre y cómo va el relay** (#28): `version`,
  `commit` y `commitVerified`, `mode` (`estándar`, `cloud` o `multiorg`) y, en
  modo estándar, `relay` con `pendientes`, `masViejoSegundos` y
  `ultimoErrorEn`. El código HTTP sigue dependiendo solo de la base.
- **El turno aguanta una caída del CRM** (#30). Si al empezar un turno el CRM
  no contesta (red, timeout, 5xx o 429), la misma ráfaga se reintenta tras
  `TURN_RETRY_DELAYS` (15 s, 45 s, 2 min y 5 min). Lo que el lead escriba
  mientras tanto sale en una sola respuesta. Si el CRM no vuelve a tiempo, la
  conversación pasa a un humano (handoff `error`) en cuanto conteste. Los
  reintentos viven en memoria: un reinicio de Nea los pierde; el mensaje no,
  porque el relay lo guarda en Postgres.
- **El cierre sin rumbo se ve en el CRM** (#28). Mientras dura, la ficha del
  contacto lleva `cierre_sin_rumbo` con la hora (el CRM raíz lo enseña como
  «Cierre sin rumbo»). Se borra al reabrir.
- **Prueba de punta a punta contra Vocero raíz** (#30).
  `scripts/e2e_contra_raiz.py` monta el par en modo estándar, hace de Meta y
  de cliente, y comprueba nueve historias en el CRM. Cuesta unos centavos de
  modelo.
- **Pruebas de `PgStore` contra un Postgres de verdad** (#27):
  `tests/test_pg_store.py`, con su propio job de CI (`postgres:16`).

### Cambió

- **`META_APP_SECRET` es obligatoria en modo estándar** (#32). Antes, vacía,
  `/webhook` aceptaba cualquier POST sin firma: quien conociera la URL podía
  hacerse pasar por un lead y hacer que Nea le contestara y gastara modelo.
  Ahora, sin secreto o con la firma ausente o inválida, responde 401. En modo
  cloud `/webhook` ya no se monta: la única entrada es el despacho firmado del
  CRM.
- **La imagen corre sin root** (#32): usuario `nea`, UID y GID 10001.
- **Límites de entrada** (#32). El cuerpo de `/webhook` y del despacho, hasta
  2 MiB (más, 413). La descarga de un adjunto, hasta 16 MiB y 30 s (antes,
  60 s). El texto de un PDF se extrae en un proceso aparte, con 6 s de tope y
  dos a la vez, para que un PDF pesado no frene los turnos de los demás.
- **El candado de cierre se reabre** (#28). Antes, tras la despedida había
  24 h de silencio pasara lo que pasara: un «¿cuánto cuesta?» se quedaba sin
  respuesta. Ahora el relleno («gracias», «ok 👍») se sigue contestando con
  silencio durante `STALL_COOLDOWN_HOURS`, pero un mensaje con contenido
  reabre en el acto y los contadores vuelven a cero. Los umbrales se ajustan
  con `STALL_MAX_TURNS`, `STALL_FILLER_STREAK` y `STALL_COOLDOWN_HOURS`, con
  los valores de siempre por defecto. Y «ok 👍» o «va, gracias 🙏» ahora
  cuentan como relleno.
- **Tope por intento al modelo** (#27): `LLM_TIMEOUT_SECONDS` (45 s), al
  conversar y al transcribir, y el SDK ya no reintenta por su cuenta. Antes un
  proveedor colgado podía tener al lead media hora en «escribiendo…» antes
  del handoff `error`.
- **La agenda se vuelve a preguntar** cada `AGENDA_PROBE_TTL_SECONDS` (60 s)
  (#27). Encender o apagar `AGENDA` en el CRM ya no exige reiniciar Nea.
- **El relay se pone al día en un minuto** (#27, #30). La espera entre
  intentos tiene tope de `RELAY_BACKOFF_CAP_SECONDS` (60 s; antes, 15 min), y
  un barrido vacía toda la cola vencida, no solo 50 filas.
- **Sin agenda v2, Nea no ofrece recordatorios** (#30). El CRM raíz no los
  manda: `book_session` ya no pide `recordatorios_aceptados` y el prompt dice
  que por aquí no hay recordatorios. Con la agenda v2 de Vocero Cloud todo
  sigue igual.
- **Un NUNCA más en `app/prompt.py`** (#30): no ofrecer ni prometer una acción
  que Nea no puede hacer con sus herramientas (llamar, mandar un correo,
  escribir más tarde, avisar, apartar un lugar). Ninguno de los NUNCA de antes
  se relajó.
- **La confirmación de la cita dice «Enlace de la reunión:»** (#27), no
  «Enlace de Zoom:»: el CRM no dice de qué proveedor es la sala.
- **Dependencias con versión exacta** en `requirements*.txt` (#27): lo que
  pasó las pruebas es lo que se despliega.

### Corregido

- **Modo estándar: el relay no le pasaba nada al CRM** (#27). Desde `95549c8`
  (31-ago, #12), `PgStore.due_relays` leía columnas que `relay_queue` no tiene
  y el worker se tragaba el error cada 5 s. Sin relay, ningún mensaje entrante
  llegaba a la bandeja, los estados de entrega no avanzaban, a un contacto
  nuevo Nea no le contestaba nunca (`/api/bot/context` daba 404) y a los
  conocidos solo mientras su último mensaje relevado tuviera menos de 24 h. El
  modo cloud no usa relay y no se vio afectado.
- **Markdown en WhatsApp** (#28). El lead veía `**$800**`, `## Precios`,
  tablas con barras y `[Agenda](https://…)`. Ahora `app/formato.py` lo
  convierte al formato de WhatsApp antes de enviar, en el turno y en el
  seguimiento, sin tocar URL ni correos. El historial guarda lo convertido.
- **Quien escribe sin compartir su número no recibía respuesta** (#28). Nea
  mandaba el BSUID pelón y el CRM lo guarda como `bsuid:<id>`: el contexto
  daba 404. `ALLOWED_WA_IDS` y `TESTER_WA_IDS` aceptan el BSUID con o sin el
  prefijo.
- **Un turno que revienta** por algo inesperado deja, además del log, un
  handoff `error` en la conversación (#27).
- **Un 404 del CRM ya no apaga la agenda de todo el proceso** (#27). Solo el
  404 vacío quiere decir «agenda apagada»; un 404 con el sobre de error del
  CRM es una conversación o una cita que no existe.
- **Contra un CRM que ignora la fecha pedida, Nea no niega la tarde** (#30).
  Dice qué horarios ve, avisa que es solo una parte y ofrece que el equipo
  confirme la hora o revisar otro día, en vez de «mañana solo tengo por la
  mañana».
- **El token del webhook del CRM ya no queda en el log de Nea** (#30). httpx
  escribía la URL de cada relay, con el token en la ruta.
- **Modo cloud: un despacho confirmado ya no se pierde si Nea se cae** (#32).
  Antes Nea respondía 200 al CRM con el turno solo en memoria. Ahora lo guarda
  en `dispatch_inbox` antes de confirmar y un worker lo retoma al arrancar. Un
  turno que se cortó a medias pasa a un humano en vez de repetirse, para no
  mandarle dos veces lo mismo al lead.

### Actualizar

Basta con correr la versión nueva: las migraciones se aplican solas y todas
las variables nuevas traen default. En modo cloud no hay relay: los puntos 2
y 6 no aplican.

**Antes, en modo estándar: comprueba que `META_APP_SECRET` tenga el App
Secret de tu app de Meta** (la misma del token). Si estaba vacía, desde esta
versión `POST /webhook` responde 401 y en el log de Nea aparece
`firma inválida o ausente en el webhook — 401`.

1. **¿Qué versión corres?** Si tu `/health` no trae `version`, tu Nea es de
   antes del 22-sep. Si dice `dev`, se construyó sin los build args.
2. **Modo estándar con un `main` de entre el 31-ago y el 21-sep** (de
   `95549c8` a antes de #27): el CRM no está recibiendo tus mensajes. En el
   log de Nea se ve como `relay: fallo procesando la cola` con
   `KeyError: 'organization_id'`, cada 5 s. Al actualizar, el primer barrido
   le entrega al CRM lo que tenga menos de 24 h y abandona lo más viejo (su
   cuerpo crudo se queda en `relay_queue`). A los leads que escribieron esos
   días y no recibieron respuesta nadie les contesta solo: revísalos en la
   bandeja.
3. **Pásate a la imagen** (recomendado). En Coolify, lo más limpio es una app
   nueva: + New → Docker Image, `ghcr.io/kevinrivm/nea-agent:1.0.0`, con las
   mismas variables, la misma base y el mismo dominio. Detén la vieja antes de
   arrancar la nueva: dos Nea contra la misma base reenvían dos veces lo
   pendiente. No pongas `NEA_VERSION` en las variables y deja `PORT` en 8000.
   La imagen corre como UID 10001: si montas el `BRIEF_PATH` desde un volumen,
   que ese usuario pueda leerlo.
   Si prefieres construir, hazlo desde el tag `v1.0.0` con los build args del
   README.
4. **Migraciones.** Se aplican solas al arrancar, antes de atender:
   - `006_stall_reapertura.sql`: `bot_conversation.stall_since_message_id`
     (`BIGINT NOT NULL DEFAULT 0`).
   - `007_relay_ultimo_error.sql`: `relay_queue.last_error_at` y su índice
     parcial.
   - `008_dispatch_inbox.sql`: la tabla `dispatch_inbox`. Solo la usa el modo
     cloud; en modo estándar se queda vacía.

   Son aditivas (`ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`): no
   borran ni reescriben datos.
5. **Variables nuevas.** Ninguna es obligatoria (la que cambió es
   `META_APP_SECRET`, arriba):

   | Variable | Default | Antes |
   |---|---|---|
   | `LLM_TIMEOUT_SECONDS` | `45` | Hasta 600 s por petición, y el SDK reintentaba dos veces más |
   | `AGENDA_PROBE_TTL_SECONDS` | `60` | Se preguntaba solo al arrancar |
   | `STALL_MAX_TURNS` | `14` | 14, fijo |
   | `STALL_FILLER_STREAK` | `3` | 3, fijo |
   | `STALL_COOLDOWN_HOURS` | `24` | 24, fijo |
   | `TURN_RETRY_DELAYS` | `15,45,120,300` | Sin reintentos: el turno se perdía |
   | `RELAY_BACKOFF_CAP_SECONDS` | `60` | 900 (15 min) |

6. **Si Meta le manda los webhooks a Nea por un override de la WABA, pásalo
   al del número** (README, «El webhook de Meta, a Nea»). Vocero raíz hasta
   1.3.0 lo borra cada vez que guardas la conexión de WhatsApp, y Nea deja de
   recibir sin aviso. Revisa a dónde llegan hoy con
   `GET /{PHONE_NUMBER_ID}?fields=webhook_configuration`.
7. **Si tu fork cambió `app/prompt.py`**, trae lo que agregó #30: el NUNCA de
   las acciones sin herramienta y el aviso de que no hay recordatorios. Es lo
   que evita que Nea prometa recordatorios que la raíz no manda.
8. **Comprueba**: `/health` con `"version": "1.0.0"`, `"mode": "estándar"` y
   `relay.pendientes` bajando a 0; un mensaje de prueba llega a la bandeja del
   CRM y Nea contesta.

**Si tu copia es anterior al 18-sep**, también te llegan:

- `LLM_REASONING_EFFORT` (`minimal`) y `LLM_PROVIDER_SORT` (`throughput`)
  (18-sep, #24). Van en cada llamada al modelo; OpenRouter los entiende, y si
  un proveedor los rechaza, Nea deja de mandarlos y reintenta. Vacíos, no se
  mandan.
- Las migraciones `004_multiorg.sql` y `005_pending_dispatch.sql` (31-ago), y
  la `003_stalled.sql` (19-ago). También se aplican solas.
- Los nombres `LLM_*` (31-ago, #11). Los `OPENAI_*` siguen funcionando.
- El modo cloud (31-ago, #9 y #12). Sin `VOCERO_MODE` no se activa nada.
- `TESTER_WA_IDS` (19-ago, #5). El comando `/reset` ya no cuelga de
  `ALLOWED_WA_IDS`: si lo usas, pon tu número también en `TESTER_WA_IDS`.
