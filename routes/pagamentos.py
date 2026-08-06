import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

import mercadopago
from flask import Blueprint, abort, current_app, flash, g, redirect, session, url_for

from models import (
    atualizar_pagamento,
    atualizar_pagamento_pedido,
    atualizar_preferencia,
    atualizar_preferencia_pedido,
    itens_pedido,
    obter_pedido,
)
from routes.auth import login_required

pagamentos_bp = Blueprint("pagamentos", __name__)
API_URL = "https://api.mercadopago.com"


class MercadoPagoError(Exception):
    def __init__(self, status, detalhes):
        self.status = status
        self.detalhes = detalhes
        super().__init__(f"Mercado Pago respondeu HTTP {status}: {detalhes}")


def mensagem_erro(detalhes):
    if isinstance(detalhes, dict):
        causas = detalhes.get("cause") or detalhes.get("causes")
        if isinstance(causas, list) and causas and isinstance(causas[0], dict):
            return causas[0].get("description") or causas[0].get("code") or "dados invalidos"
        return detalhes.get("message") or detalhes.get("error") or "dados invalidos"
    return "dados invalidos"


def url_publica_https(url):
    endereco = urlparse(url)
    return endereco.scheme == "https" and endereco.hostname not in {None, "localhost", "127.0.0.1", "::1"}


def adicionar_urls(preference, url_retorno):
    base_url = current_app.config["BASE_URL"]
    if url_publica_https(base_url):
        preference.update({
            "back_urls": {"success": url_retorno, "failure": url_retorno, "pending": url_retorno},
            "auto_return": "approved",
            "notification_url": f"{base_url}/webhook/mercadopago",
        })
    else:
        current_app.logger.info("Checkout em modo local: retorno automatico e webhook aguardam BASE_URL HTTPS publica.")


def requisicao_api(metodo, caminho, corpo=None):
    token = current_app.config["MERCADOPAGO_ACCESS_TOKEN"]
    if not token:
        raise MercadoPagoError(0, {"message": "Token do Mercado Pago nao configurado"})
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    cabecalhos = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if metodo in {"POST", "PUT", "PATCH"}:
        cabecalhos["X-Idempotency-Key"] = str(uuid4())
    requisicao = Request(f"{API_URL}{caminho}", data=dados, headers=cabecalhos, method=metodo)
    try:
        with urlopen(requisicao, timeout=20) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except HTTPError as erro:
        try:
            detalhes = json.loads(erro.read().decode("utf-8"))
        except Exception:
            detalhes = {"message": "Resposta invalida da API"}
        raise MercadoPagoError(erro.code, detalhes) from erro
    except URLError as erro:
        raise MercadoPagoError(0, {"message": f"Falha de rede: {erro.reason}"}) from erro


def criar_preferencia(preference):
    token = current_app.config["MERCADOPAGO_ACCESS_TOKEN"]
    if not token:
        raise MercadoPagoError(0, {"message": "Token do Mercado Pago nao configurado"})
    resposta = mercadopago.SDK(token).preference().create(preference)
    dados = resposta.get("response", {})
    status = resposta.get("status", 0)
    if not 200 <= status < 300:
        raise MercadoPagoError(status, dados)
    preference_id = dados.get("id")
    checkout_url = dados.get("init_point") or dados.get("sandbox_init_point")
    if not preference_id or not checkout_url:
        raise MercadoPagoError(status, {"message": "A resposta nao trouxe o link do Checkout Pro"})
    return preference_id, checkout_url


def configuracao_pagamento(forma_pagamento):
    tipos_excluidos = {
        "PIX": ["credit_card", "debit_card", "ticket"],
        "CREDITO": ["debit_card", "bank_transfer", "ticket"],
        "DEBITO": ["credit_card", "bank_transfer", "ticket"],
    }
    try:
        tipos = tipos_excluidos[forma_pagamento]
    except KeyError as erro:
        raise MercadoPagoError(0, {"message": "Forma de pagamento invalida"}) from erro
    return {"excluded_payment_types": [{"id": tipo} for tipo in tipos]}


STATUS_PAGAMENTO = {
    "approved": "APROVADO",
    "pending": "PENDENTE",
    "in_process": "PENDENTE",
    "rejected": "REJEITADO",
    "cancelled": "CANCELADO",
    "refunded": "CANCELADO",
    "charged_back": "CANCELADO",
}


def sincronizar_pagamento_pedido(pedido_id, payment_id):
    pedido = obter_pedido(pedido_id)
    if pedido is None or not payment_id:
        return None
    token = current_app.config["MERCADOPAGO_ACCESS_TOKEN"]
    if not token:
        return None
    resposta = mercadopago.SDK(token).payment().get(payment_id)
    if not 200 <= resposta.get("status", 0) < 300:
        raise MercadoPagoError(resposta.get("status", 0), resposta.get("response", {}))
    pagamento = resposta.get("response", {})
    if str(pagamento.get("external_reference") or "") != f"PEDIDO:{pedido_id}":
        return None
    status = STATUS_PAGAMENTO.get(pagamento.get("status"), "PENDENTE")
    atualizar_pagamento_pedido(pedido_id, status, str(payment_id))
    return status


def cancelar_cobranca_pedido(pedido):
    if pedido["mercadopago_order_id"]:
        requisicao_api("POST", f"/v1/orders/{pedido['mercadopago_order_id']}/cancel", {})


def reembolsar_pedido(pedido):
    if pedido["mercadopago_order_id"]:
        return requisicao_api("POST", f"/v1/orders/{pedido['mercadopago_order_id']}/refund", {})
    if pedido["payment_id"]:
        return requisicao_api("POST", f"/v1/payments/{pedido['payment_id']}/refunds", {})
    raise MercadoPagoError(0, {"message": "Identificador de pagamento indisponivel para estorno"})


@pagamentos_bp.post("/pagamentos/checkout/<int:venda_id>")
@login_required
def criar_checkout(venda_id):
    from models import obter_venda
    venda = obter_venda(venda_id, g.usuario["estabelecimento_id"])
    if venda is None:
        return "Venda nao encontrada", 404
    if venda["valor_total"] <= 0:
        flash("O total da venda deve ser maior que R$ 0,00 para abrir o checkout.", "danger")
        return redirect(url_for("vendas.sucesso", venda_id=venda_id))
    preference = {
        "items": [{"title": venda["produto"], "quantity": venda["quantidade"], "unit_price": float(venda["valor_total"] / venda["quantidade"]), "currency_id": "BRL"}],
        "external_reference": str(venda["id"]),
    }
    if venda["forma_pagamento"] in {"PIX", "CREDITO", "DEBITO"}:
        preference["payment_methods"] = configuracao_pagamento(venda["forma_pagamento"])
    adicionar_urls(preference, f"{current_app.config['BASE_URL']}/cliente")
    try:
        preference_id, checkout_url = criar_preferencia(preference)
        atualizar_preferencia(venda_id, preference_id)
        return redirect(checkout_url)
    except MercadoPagoError as erro:
        current_app.logger.error("Mercado Pago recusou a preferencia (HTTP %s): %s", erro.status, erro.detalhes)
        atualizar_pagamento(venda_id, "CANCELADO")
        flash(f"O Mercado Pago recusou esta venda: {mensagem_erro(erro.detalhes)}.", "danger")
    except Exception:
        current_app.logger.exception("Falha ao criar preferencia Mercado Pago")
        atualizar_pagamento(venda_id, "CANCELADO")
        flash("Nao foi possivel abrir o checkout. Confira as credenciais e tente novamente.", "danger")
    return redirect(url_for("vendas.sucesso", venda_id=venda_id))


@pagamentos_bp.post("/pagamentos/pedido/<int:pedido_id>")
def criar_checkout_pedido(pedido_id):
    if session.get("pedido_pagamento_pendente") != pedido_id:
        abort(403)
    pedido = obter_pedido(pedido_id)
    if pedido is None:
        return "Pedido nao encontrado", 404
    itens = itens_pedido(pedido_id)
    preference = {
        "items": [{"title": item["descricao"], "quantity": item["quantidade"], "unit_price": float(item["valor_unitario"]), "currency_id": "BRL"} for item in itens],
        "external_reference": f"PEDIDO:{pedido_id}",
        "payment_methods": configuracao_pagamento(pedido["forma_pagamento"]),
    }
    if pedido["valor_entrega"] > 0:
        preference["items"].append({"title": "Taxa de entrega", "quantity": 1, "unit_price": float(pedido["valor_entrega"]), "currency_id": "BRL"})
    adicionar_urls(preference, f"{current_app.config['BASE_URL']}/cliente/retorno/{pedido['codigo_acompanhamento']}")
    try:
        preference_id, checkout_url = criar_preferencia(preference)
        atualizar_preferencia_pedido(pedido_id, preference_id)
        session.pop("pedido_pagamento_pendente", None)
        return redirect(checkout_url)
    except MercadoPagoError as erro:
        current_app.logger.error("Mercado Pago recusou o pedido %s (HTTP %s): %s", pedido_id, erro.status, erro.detalhes)
        atualizar_pagamento_pedido(pedido_id, "CANCELADO")
        flash(f"Nao foi possivel iniciar o pagamento: {mensagem_erro(erro.detalhes)}.", "danger")
    except Exception:
        current_app.logger.exception("Falha ao criar checkout do pedido %s", pedido_id)
        atualizar_pagamento_pedido(pedido_id, "CANCELADO")
        flash("Nao foi possivel iniciar o pagamento. Tente novamente.", "danger")
    session.pop("pedido_pagamento_pendente", None)
    return redirect(url_for("cliente.pedido", codigo=pedido["codigo_acompanhamento"]))
