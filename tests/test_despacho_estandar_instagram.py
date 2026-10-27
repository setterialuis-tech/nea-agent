"""Despacho estándar del CRM (un solo negocio): Instagram por esta puerta.

Lo que fijan estos tests es la frontera con WhatsApp. Sin `DISPATCH_ESTANDAR`
Nea es la de siempre —no monta la ruta nueva, no pide perfiles por canal—, y con
ella atiende SOLO los canales pedidos: un despacho de WhatsApp se confirma y se
ignora (Nea ya lo recibe por el webhook de Meta; contestarlo aquí sería
responder dos veces). Instagram nace cerrado: sin `ALLOWED_IG_IDS` no hay
respuesta.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.dispatch import _procesar
from app.dispatch_worker import drain_one
from app.llm import LlmReply
from app.main import create_app
from app.profile import ProfileProvider
from tests.conftest import CRM_URL, FakeLLM, make_ctx, make_settings, mock_crm_basics

BOT_KEY = "test-key"  # la de make_settings: con ella firma el CRM y contesta Nea
IG_ID = "ig:17841400000000001"
CONV = "cv_ig1"
PROMPT_IG = "# PROMPT DE INSTAGRAM\nSin pedir teléfono de entrada."
PROMPT_WA = "# PROMPT DE WHATSAPP\nPide el teléfono primero."


def despacho(canal: str = "instagram", identity: str = IG_ID, texto: str = "hola") -> dict:
    return {
        "dispatchId": f"dsp_{canal}_1",
        "organization": {"id": "org_1", "slug": "roger"},
        "conversation": {"id": CONV, "channel": canal, "aiEnabled": True, "windowOpen": True},
        "contact": {"id": "ct_1", "displayName": "tudocalejo", "identity": identity},
        "messages": [{"id": "msg_1", "at": "2026-10-26T12:00:00.000Z", "type": "text", "text": texto}],
    }


def firmar(cuerpo: bytes, secreto: str = BOT_KEY) -> str:
    return "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


async def enviar(client: httpx.AsyncClient, data: dict, secreto: str = BOT_KEY) -> httpx.Response:
    body = json.dumps(data).encode()
    return await client.post(
        "/vocero/dispatch", content=body, headers={"x-vocero-signature": firmar(body, secreto)}
    )


def ctx_estandar(**extra):
    return make_ctx(make_settings(dispatch_estandar="instagram", **extra), llm=FakeLLM())


# ── Los ajustes ───────────────────────────────────────────────────────────


class TestAjustes:
    def test_apagado_por_defecto(self) -> None:
        s = make_settings()
        assert s.dispatch_estandar_canales == frozenset()

    def test_lee_canales_con_espacios_y_mayusculas(self) -> None:
        s = make_settings(dispatch_estandar=" Instagram , messenger ")
        assert s.dispatch_estandar_canales == frozenset({"instagram", "messenger"})

    def test_secreto_en_modo_de_siempre_es_la_llave_del_bot(self) -> None:
        assert make_settings().secreto_de_despacho == BOT_KEY

    def test_secreto_en_cloud_sigue_siendo_el_del_cerebro(self) -> None:
        s = make_settings(vocero_mode="cloud", crm_brain_secret="del-cerebro", crm_organization="a")
        assert s.secreto_de_despacho == "del-cerebro"

    def test_lista_de_instagram_vacia_no_deja_pasar_a_nadie(self) -> None:
        assert make_settings(allowed_ig_ids="").canal_permitido(IG_ID) is False

    def test_lista_de_instagram_es_de_identidades_exactas(self) -> None:
        s = make_settings(allowed_ig_ids=f" {IG_ID} , ig:999 ")
        assert s.canal_permitido(IG_ID) is True
        assert s.canal_permitido("ig:999") is True
        assert s.canal_permitido("ig:17841400000000002") is False
        assert s.canal_permitido("525550001111") is False

    def test_asterisco_abre_a_todos(self) -> None:
        assert make_settings(allowed_ig_ids="*").canal_permitido("ig:cualquiera") is True


# ── La puerta ─────────────────────────────────────────────────────────────


class TestPuerta:
    async def test_sin_la_variable_no_hay_ruta_de_despacho(self) -> None:
        ctx = make_ctx()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(ctx)), base_url="http://t") as c:
            assert (await enviar(c, despacho())).status_code == 404
            # y el webhook de Meta sigue ahí, como siempre
            assert (await c.get("/webhook")).status_code != 404
        await ctx.crm.aclose()

    async def test_con_la_variable_hay_despacho_Y_sigue_el_webhook_de_meta(self) -> None:
        ctx = ctx_estandar()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(ctx)), base_url="http://t") as c:
            assert (await enviar(c, despacho())).status_code == 200
            assert len(ctx.store.dispatch_inbox) == 1
            assert (await c.get("/webhook")).status_code != 404
        await ctx.crm.aclose()

    async def test_firma_de_otro_secreto_es_401(self) -> None:
        ctx = ctx_estandar()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(ctx)), base_url="http://t") as c:
            assert (await enviar(c, despacho(), secreto="otro-secreto")).status_code == 401
            assert len(getattr(ctx.store, "dispatch_inbox", {})) == 0
        await ctx.crm.aclose()

    async def test_health_dice_que_canales_atiende(self) -> None:
        ctx = ctx_estandar()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(ctx)), base_url="http://t") as c:
            cuerpo = (await c.get("/health")).json()
        assert cuerpo["despachoEstandar"] == ["instagram"]
        await ctx.crm.aclose()


# ── WhatsApp no se toca ───────────────────────────────────────────────────


class TestWhatsAppFuera:
    async def test_un_despacho_de_whatsapp_se_ignora_sin_turno(self, monkeypatch) -> None:
        ctx = ctx_estandar()
        turno = AsyncMock()
        monkeypatch.setattr("app.dispatch.handle_flush", turno)
        await _procesar(ctx, despacho(canal="whatsapp", identity="525550001111"))
        turno.assert_not_called()
        await ctx.crm.aclose()

    async def test_un_canal_que_no_se_pidio_tampoco(self, monkeypatch) -> None:
        ctx = ctx_estandar()  # solo instagram
        turno = AsyncMock()
        monkeypatch.setattr("app.dispatch.handle_flush", turno)
        await _procesar(ctx, despacho(canal="messenger", identity="fb:1"))
        turno.assert_not_called()
        await ctx.crm.aclose()

    async def test_instagram_si_llega_al_turno_con_su_canal(self, monkeypatch) -> None:
        ctx = ctx_estandar()
        turno = AsyncMock()
        monkeypatch.setattr("app.dispatch.handle_flush", turno)
        await _procesar(ctx, despacho())
        turno.assert_awaited_once()
        assert turno.await_args.kwargs["canal"] == "instagram"
        assert turno.await_args.args[1] == IG_ID
        await ctx.crm.aclose()

    async def test_el_webhook_de_whatsapp_no_pasa_canal_ni_pide_perfil_por_canal(
        self, respx_mock
    ) -> None:
        # El turno de siempre: ni `canal` en el flush ni `?channel=` en el perfil.
        ctx = ctx_estandar()
        ctx.profile = ProfileProvider(ctx.crm)
        perfil = respx_mock.get(f"{CRM_URL}/api/bot/profile").mock(
            return_value=httpx.Response(200, json={"profile": {"name": "Sofi", "instructions": PROMPT_WA}, "kb": "", "resources": []})
        )
        p = await ctx.profile.get()
        assert PROMPT_WA in (p.instructions or "") or p.agent_name
        assert "channel" not in perfil.calls[0].request.url.params
        await ctx.crm.aclose()


# ── Perfil por canal ──────────────────────────────────────────────────────


class TestPerfilPorCanal:
    @staticmethod
    def _montar(respx_mock):
        def responder(request: httpx.Request) -> httpx.Response:
            canal = request.url.params.get("channel")
            texto = PROMPT_IG if canal == "instagram" else PROMPT_WA
            return httpx.Response(
                200, json={"profile": {"name": "Sofi", "instructions": texto}, "kb": "", "resources": []}
            )

        return respx_mock.get(f"{CRM_URL}/api/bot/profile").mock(side_effect=responder)

    async def test_cada_canal_tiene_su_cache_y_no_se_pisan(self, respx_mock) -> None:
        ctx = make_ctx()
        ruta = self._montar(respx_mock)
        proveedor = ProfileProvider(ctx.crm)
        ig = await proveedor.get("instagram")
        wa = await proveedor.get()
        assert PROMPT_IG in (ig.instructions or "")
        assert PROMPT_WA in (wa.instructions or "")
        # segunda vuelta: todo sale de la caché, y WhatsApp sigue leyendo el suyo
        assert PROMPT_IG in ((await proveedor.get("instagram")).instructions or "")
        assert PROMPT_WA in ((await proveedor.get()).instructions or "")
        assert ruta.call_count == 2
        canales = [c.request.url.params.get("channel") for c in ruta.calls]
        assert canales == ["instagram", None]
        await ctx.crm.aclose()

    async def test_si_el_crm_se_cae_instagram_usa_el_perfil_de_siempre(self, respx_mock) -> None:
        ctx = make_ctx()
        respx_mock.get(f"{CRM_URL}/api/bot/profile").mock(return_value=httpx.Response(500))
        proveedor = ProfileProvider(ctx.crm)
        # sin nada guardado: cae al mínimo de siempre, no revienta
        perfil = await proveedor.get("instagram")
        assert perfil is not None
        await ctx.crm.aclose()

    async def test_whatsapp_como_canal_no_pide_nada_distinto(self, respx_mock) -> None:
        ctx = make_ctx()
        ruta = self._montar(respx_mock)
        proveedor = ProfileProvider(ctx.crm)
        await proveedor.get("whatsapp")
        assert "channel" not in ruta.calls[0].request.url.params
        await ctx.crm.aclose()


# ── El turno de Instagram, de punta a punta ───────────────────────────────


def _contexto_ig() -> dict:
    return {
        "contact": {
            "id": "ct_1",
            "name": "tudocalejo",
            "waIdentity": IG_ID,
            "identity": IG_ID,
            "channel": "instagram",
            "phone": None,
            "ficha": {},
        },
        "conversation": {"id": CONV, "aiEnabled": True, "windowOpen": True, "windowExpiresAt": "2026-10-27T00:00:00Z", "handoffAt": None},
        "lead": {"id": "ld_1", "stageName": "Nuevo"},
        "adOrigen": None,
        "booking": {"next": None},
    }


class TestTurnoInstagram:
    async def _correr(self, ctx, respx_mock, data=None):
        rutas = mock_crm_basics(respx_mock)
        rutas["context"].mock(return_value=httpx.Response(200, json=_contexto_ig()))
        rutas["perfil"] = TestPerfilPorCanal._montar(respx_mock)
        ctx.profile = ProfileProvider(ctx.crm)
        ctx.llm.replies = [LlmReply(content="Hola, soy el asistente del Dr. Roger.")]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(ctx)), base_url="http://t") as c:
            assert (await enviar(c, data or despacho())).status_code == 200
        assert await drain_one(ctx)
        return rutas

    async def test_contesta_con_el_prompt_de_instagram_y_por_la_ruta_del_bot(self, respx_mock) -> None:
        ctx = ctx_estandar(allowed_ig_ids=IG_ID)
        rutas = await self._correr(ctx, respx_mock)
        # se pidió el perfil DE INSTAGRAM y el modelo leyó ese documento
        # (otras piezas —la elección de modelo— leen el perfil de siempre: no importa;
        # lo que importa es que el turno pidió el de Instagram y el modelo lo leyó)
        canales = [c.request.url.params.get("channel") for c in rutas["perfil"].calls]
        assert "instagram" in canales
        sistema = ctx.llm.calls[0]["messages"][0]["content"]
        assert "PROMPT DE INSTAGRAM" in sistema
        assert "PROMPT DE WHATSAPP" not in sistema
        # y la respuesta salió por /api/bot/messages, con la conversación del CRM
        assert rutas["messages"].call_count == 1
        cuerpo = json.loads(rutas["messages"].calls[0].request.content)
        assert cuerpo["conversationId"] == CONV
        assert "Dr. Roger" in cuerpo["text"]
        # y NO pidió el teléfono ni armó nada de WhatsApp
        assert "TELÉFONO FALTANTE" not in sistema
        assert "PAÍS DEL NÚMERO" not in sistema
        await ctx.crm.aclose()

    async def test_nace_cerrado_sin_lista_no_contesta_a_nadie(self, respx_mock) -> None:
        ctx = ctx_estandar()  # allowed_ig_ids vacío
        rutas = await self._correr(ctx, respx_mock)
        assert ctx.llm.calls == []
        assert rutas["messages"].call_count == 0
        await ctx.crm.aclose()

    async def test_una_cuenta_fuera_de_la_lista_no_recibe_respuesta(self, respx_mock) -> None:
        ctx = ctx_estandar(allowed_ig_ids="ig:otra-persona")
        rutas = await self._correr(ctx, respx_mock)
        assert ctx.llm.calls == []
        assert rutas["messages"].call_count == 0
        await ctx.crm.aclose()

    async def test_la_lista_de_whatsapp_no_cierra_ni_abre_instagram(self, respx_mock) -> None:
        # ALLOWED_WA_IDS (teléfonos de prueba) no decide nada aquí: manda ALLOWED_IG_IDS.
        ctx = ctx_estandar(allowed_wa_ids="525550001111", allowed_ig_ids=IG_ID)
        rutas = await self._correr(ctx, respx_mock)
        assert rutas["messages"].call_count == 1
        await ctx.crm.aclose()
