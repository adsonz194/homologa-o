import hashlib
import hmac

import mercadopago
from flask import Blueprint, current_app, jsonify, request

from models import (
    atualizar_pagamento,
    atualizar_pagamento_pedido,
    obter_venda_por_ordem_point,
    obter_segredo_webhook_mercadopago,
    obter_token_mercadopago,
)
from routes.pagamentos import STATUS_PAGAMENTO
from routes.pagamentos import sincronizar_ordem_point_venda

webhook_bp = Blueprint("webhook", __name__)


def assinatura_valida():
    """Valida a assinatura HMAC do webhook quando ela esta configurada."""
    segredo = obter_segredo_webhook_mercadopago()
    if not segredo:
        return True
    assinatura = request.headers.get("x-signature", "")
    request_id = request.headers.get("x-request-id", "")
    data_id = request.args.get("data.id", "")
    partes = {}
    for parte in assinatura.split(","):
        chave, separador, valor = parte.strip().partition("=")
        if separador and chave in {"ts", "v1"}:
            partes[chave] = valor.strip()
    timestamp = partes.get("ts", "")
    recebida = partes.get("v1", "")
    if not request_id or not data_id or not timestamp or not recebida:
        return False
    manifesto = f"id:{data_id};request-id:{request_id};ts:{timestamp};"
    esperada = hmac.new(segredo.encode("utf-8"), manifesto.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, recebida)


@webhook_bp.post("/webhook/mercadopago")
def receber_webhook():
    if not assinatura_valida():
        current_app.logger.warning("Webhook Mercado Pago recusado: assinatura invalida.")
        return jsonify(erro="Assinatura invalida"), 401
    payload = request.get_json(silent=True) or request.form.to_dict()
    tipo = str(payload.get("type") or payload.get("topic") or "").lower()
    dados = payload.get("data", {})
    recurso_id = dados.get("id") or payload.get("id")
    if not recurso_id:
        return jsonify(recebido=True), 200
    try:
        if tipo == "order":
            # Orders do Point carregam a referencia VENDA-<id>. A consulta
            # confirma o status final antes de alterar estoque/pagamento.
            venda = obter_venda_por_ordem_point(str(recurso_id))
            if venda is not None:
                sincronizar_ordem_point_venda(venda["id"], venda["estabelecimento_id"])
        elif tipo == "payment":
            token = obter_token_mercadopago()
            if not token:
                return jsonify(erro="Token nao configurado"), 500
            pagamento = mercadopago.SDK(token).payment().get(recurso_id)["response"]
            referencia = str(pagamento.get("external_reference") or "")
            status = STATUS_PAGAMENTO.get(pagamento.get("status"), "PENDENTE")
            if referencia.startswith("PEDIDO:"):
                atualizar_pagamento_pedido(int(referencia.split(":", 1)[1]), status, str(recurso_id))
            elif referencia.startswith("VENDA-") and referencia[6:].isdigit():
                atualizar_pagamento(int(referencia[6:]), status, str(recurso_id))
            elif referencia.isdigit():
                atualizar_pagamento(int(referencia), status, str(recurso_id))
    except Exception:
        current_app.logger.exception("Falha ao processar webhook do Mercado Pago")
        return jsonify(erro="Falha temporaria"), 500
    return jsonify(recebido=True), 200
