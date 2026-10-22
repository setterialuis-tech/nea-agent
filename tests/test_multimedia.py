"""Los mismos casos que `tests/unit/formatear.test.ts` del CRM: las dos
implementaciones de `extraer_secuencia` tienen que dar lo mismo."""
from app.multimedia import Archivo, Texto, extraer_secuencia, leer_salida_formato, tipo_de_archivo

IMG = "https://i.postimg.cc/0yCfSz4Z/pacientes-extrajeros-Web.jpg"
PAGINA = "https://www.cirugiadiabetesobesidad.com/internacional/"


def test_tipo_de_archivo_por_extension():
    assert tipo_de_archivo(IMG) == "image"
    assert tipo_de_archivo("https://files.catbox.moe/9hfwag.mp4") == "video"
    assert tipo_de_archivo("https://x.com/brochure.PDF?v=2") == "document"


def test_paginas_no_son_archivos():
    assert tipo_de_archivo(PAGINA) is None
    assert tipo_de_archivo("https://www.youtube.com/shorts/lTlgTr_AZTM") is None
    assert tipo_de_archivo("https://maps.google.com/?q=Clínica+Higea+Cartagena") is None
    assert tipo_de_archivo("https://wa.me/573001112233") is None


def test_sin_archivos_un_solo_texto_intacto():
    t = "Hola Rodrigo. ¿Cuál es tu peso?"
    assert extraer_secuencia(t) == [Texto(t)]


def test_caso_4_exterior():
    t = "\n".join([
        "Gracias, Rodrigo. El primer paso es una teleconsulta. Después recibes tu propuesta en USD. Mira cómo se arma 👇",
        f"📸 {IMG}",
        f"Aquí puedes ver el proceso completo: {PAGINA} ¿Te gustaría avanzar con tu teleconsulta?",
    ])
    assert extraer_secuencia(t) == [
        Texto("Gracias, Rodrigo. El primer paso es una teleconsulta. Después recibes tu propuesta en USD."),
        Archivo(IMG, "image", "Mira cómo se arma 👇"),
        Texto(f"Aquí puedes ver el proceso completo: {PAGINA} ¿Te gustaría avanzar con tu teleconsulta?"),
    ]


def test_caption_explicito_manda_sobre_la_frase_de_presentacion():
    t = "Mira este video: 🎥 https://files.catbox.moe/9hfwag.mp4\nCaption: Así funciona el balón"
    assert extraer_secuencia(t) == [
        Texto("Mira este video:"),
        Archivo("https://files.catbox.moe/9hfwag.mp4", "video", "Así funciona el balón"),
    ]


def test_dos_imagenes_seguidas_solo_la_primera_lleva_la_frase():
    a = "https://i.postimg.cc/3JscVTMp/antes-y-depues-190-k.jpg"
    b = "https://i.postimg.cc/qBYb6Tv2/antes-y-despus-190-k-2.jpg"
    t = f"Hemos ayudado a cientos de pacientes. Mira algunos de nuestros resultados:\n📸 {a}\n📸 {b}"
    assert extraer_secuencia(t) == [
        Texto("Hemos ayudado a cientos de pacientes."),
        Archivo(a, "image", "Mira algunos de nuestros resultados:"),
        Archivo(b, "image", None),
    ]


def test_la_puntuacion_pegada_no_es_de_la_url():
    r = extraer_secuencia(f"Mira esto ({IMG}).")
    assert any(isinstance(i, Archivo) and i.url == IMG for i in r)


def test_pdf_como_documento():
    assert extraer_secuencia("Te dejo la guía: https://x.com/guia.pdf") == [
        Archivo("https://x.com/guia.pdf", "document", "Te dejo la guía:")
    ]


def test_youtube_y_paginas_se_quedan_como_texto():
    t = "Mira el video: https://www.youtube.com/shorts/lTlgTr_AZTM y más en " + PAGINA
    assert extraer_secuencia(t) == [Texto(t)]


def test_frase_sin_dos_puntos_ni_flecha_se_queda_en_el_texto():
    r = extraer_secuencia(f"Te dejo el paso a paso del proceso completo. {IMG}")
    assert r[0] == Texto("Te dejo el paso a paso del proceso completo.")
    assert r[1] == Archivo(IMG, "image", None)


def test_leer_salida_formato_n8n_y_simple():
    n8n = {"response": {"part_1": "Hola", "part_2": "", "part_3": "¿Qué tal?", "part_4": "", "image_urls": [IMG]}}
    assert leer_salida_formato(n8n) == ["Hola", "¿Qué tal?"]
    assert leer_salida_formato({"partes": ["a", " ", "b"]}) == ["a", "b"]
    assert leer_salida_formato(None) is None
    assert leer_salida_formato({"response": {"part_1": ""}}) is None
    assert leer_salida_formato("texto") is None


def test_tope_cuenta_los_archivos_y_pliega_el_texto_que_sigue_al_pie():
    from app.multimedia import ajustar_a_tope

    t = Texto("a" * 300)
    f = Archivo(IMG, "image", "Mira cómo se arma 👇")
    sig = Texto("Aquí el enlace ¿Quieres avanzar?")
    # Tope 3: texto + imagen + texto (1 + 1 + 1), nada se pliega.
    items, cuotas = ajustar_a_tope([t, f, sig], 3)
    assert items == [t, f, sig] and cuotas == [1, 0, 1]
    # Tope 2: no cabe un mensaje por bloque → el texto de después pasa al pie de la imagen.
    items, cuotas = ajustar_a_tope([t, f, sig], 2)
    assert items == [t, Archivo(IMG, "image", "Mira cómo se arma 👇\n\nAquí el enlace ¿Quieres avanzar?")]
    assert cuotas == [1, 0]
    # Tope 5: lo que sobra se reparte, más al bloque largo.
    items, cuotas = ajustar_a_tope([t, f, sig], 5)
    assert cuotas == [3, 0, 1]
    # Sin archivos el tope es el de siempre.
    assert ajustar_a_tope([t], 3) == ([t], [3])


def test_tope_no_pliega_si_el_pie_no_cabe_y_nunca_deja_un_bloque_sin_mensaje():
    from app.multimedia import ajustar_a_tope

    t = Texto("a" * 100)
    f = Archivo(IMG, "image", None)
    largo = Texto("b" * 1100)  # no cabe en 1024
    items, cuotas = ajustar_a_tope([t, f, largo], 2)
    assert items == [t, f, largo] and cuotas == [1, 0, 1]  # se pasa del tope antes que perder texto
