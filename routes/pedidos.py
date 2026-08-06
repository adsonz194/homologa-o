from io import BytesIO

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, send_file, url_for

from models import (
    atualizar_pagamento_pedido,
    atualizar_status_operacional_pedido,
    liberar_estoque_pedido,
    itens_pedido,
    listar_pedidos,
    listar_pedidos_aprovados_apos,
    obter_estabelecimento,
    obter_pedido,
)
from nota_pdf import gerar_comprovante_pedido_pdf
from routes.auth import login_required
from routes.pagamentos import MercadoPagoError, cancelar_cobranca_pedido, reembolsar_pedido

pedidos_bp = Blueprint("pedidos", __name__)
STATUS_OPERACIONAIS = {
    "PENDENTE", "FILA_DE_ESPERA", "PREPARANDO", "PRONTO",
    "SAIU_PARA_ENTREGA", "ENTREGUE", "CANCELADO", "EXTRAVIADO",
}
STATUS_OPERACIONAIS_FUNCIONARIO = {
    "PENDENTE", "FILA_DE_ESPERA", "PREPARANDO", "PRONTO", "SAIU_PARA_ENTREGA", "ENTREGUE",
}


@pedidos_bp.get("/pedidos")
@login_required
def index():
    pedidos = listar_pedidos(g.usuario["estabelecimento_id"])
    ultimo_pedido_aprovado = max(
        (pedido["id"] for pedido in pedidos if pedido["status_pagamento"] == "APROVADO"), default=0
    )
    return render_template(
        "pedidos.html", pedidos=pedidos, ultimo_pedido_aprovado=ultimo_pedido_aprovado,
        pode_gerenciar_excecoes=g.usuario["papel"] == "DONO",
    )


@pedidos_bp.get("/pedidos/notificacoes")
@login_required
def notificacoes():
    try:
        depois_id = max(0, int(request.args.get("depois", "0")))
    except ValueError:
        depois_id = 0
    pedidos = listar_pedidos_aprovados_apos(g.usuario["estabelecimento_id"], depois_id)
    return jsonify(pedidos=[{
        "id": pedido["id"], "cliente": pedido["cliente"], "total": pedido["valor_total"],
        "local_entrega": pedido["local_entrega"],
    } for pedido in pedidos])


@pedidos_bp.get("/pedidos/<int:pedido_id>/nota.pdf")
@login_required
def nota_pdf(pedido_id):
    pedido = obter_pedido(pedido_id)
    if pedido is None or pedido["estabelecimento_id"] != g.usuario["estabelecimento_id"]:
        return "Pedido nao encontrado", 404
    estabelecimento = obter_estabelecimento(pedido["estabelecimento_id"])
    if estabelecimento is None:
        return "Estabelecimento nao encontrado", 404
    conteudo = gerar_comprovante_pedido_pdf(pedido, itens_pedido(pedido_id), estabelecimento)
    return send_file(
        BytesIO(conteudo),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"pedido-{pedido_id}.pdf",
        max_age=0,
    )


@pedidos_bp.post("/pedidos/<int:pedido_id>/status")
@login_required
def atualizar_status(pedido_id):
    pedido = obter_pedido(pedido_id)
    if pedido is not None and pedido["estabelecimento_id"] != g.usuario["estabelecimento_id"]:
        pedido = None
    status = request.form.get("status_operacional", "")
    if pedido is None:
        return "Pedido nao encontrado", 404
    if status not in STATUS_OPERACIONAIS:
        flash("Status operacional invalido.", "danger")
        return redirect(url_for("pedidos.index"))
    if g.usuario["papel"] != "DONO" and (
        status not in STATUS_OPERACIONAIS_FUNCIONARIO
        or pedido["status_operacional"] in {"CANCELADO", "EXTRAVIADO"}
    ):
        flash("Funcionarios nao podem cancelar, extraviar ou reabrir pedidos finalizados.", "danger")
        return redirect(url_for("pedidos.index"))
    if status == "CANCELADO" and pedido["status_operacional"] != "CANCELADO":
        try:
            if pedido["status_pagamento"] == "APROVADO":
                reembolsar_pedido(pedido)
                atualizar_pagamento_pedido(pedido_id, "CANCELADO")
                flash("Pedido cancelado e estorno solicitado ao Mercado Pago.", "success")
            else:
                cancelar_cobranca_pedido(pedido)
                atualizar_pagamento_pedido(pedido_id, "CANCELADO")
                flash("Pedido cancelado e estoque devolvido.", "success")
        except MercadoPagoError as erro:
            flash(f"O Mercado Pago nao confirmou o cancelamento/estorno: {erro.detalhes}", "danger")
            return redirect(url_for("pedidos.index"))
        liberar_estoque_pedido(pedido_id)
    atualizar_status_operacional_pedido(pedido_id, status)
    if status != "CANCELADO":
        flash("Status operacional atualizado.", "success")
    return redirect(url_for("pedidos.index"))
