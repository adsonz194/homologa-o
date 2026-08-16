from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO

from flask import Blueprint, flash, g, redirect, render_template, request, send_file, url_for

from models import (
    EstoqueInsuficiente,
    adicionar_item_comanda,
    atualizar_pagamento,
    criar_comanda,
    data_hora_loja,
    listar_itens_venda,
    listar_vendas,
    obter_comanda_aberta,
    obter_estabelecimento,
    obter_produto,
    obter_venda,
    preparar_comanda_para_pagamento,
    relatorio_vendas,
    remover_item_comanda,
)
from routes.auth import permission_required


vendas_bp = Blueprint("vendas", __name__)
FORMAS_PAGAMENTO = {"DINHEIRO", "POINT"}


def _valor_monetario(valor):
    return float(Decimal(str(valor or "0").replace(",", ".")))


def _valor_monetario_opcional(valor):
    texto = str(valor or "").strip()
    return _valor_monetario(texto) if texto else None


def _pagina_iniciar_pagamento(venda):
    point = venda["forma_pagamento"] == "POINT"
    return render_template(
        "iniciar_pagamento.html",
        destino=url_for(
            "pagamentos.criar_cobranca_point" if point else "pagamentos.criar_checkout",
            venda_id=venda["id"],
        ),
        titulo="Enviando para a maquininha" if point else "Preparando o checkout",
        descricao=(
            "A cobranca sera exibida no terminal Mercado Pago Point."
            if point else "Abrindo o ambiente seguro do Mercado Pago."
        ),
        auto_submit=True,
    )


def _concluir_cobranca(venda):
    """Registra dinheiro no caixa ou envia a cobranca ao Point."""
    if venda["forma_pagamento"] == "DINHEIRO":
        atualizar_pagamento(venda["id"], "APROVADO")
        flash("Pagamento em dinheiro registrado. Ticket fechado.", "success")
        return redirect(url_for("vendas.sucesso", venda_id=venda["id"]))
    return _pagina_iniciar_pagamento(venda)


def _ler_item_formulario():
    produto_id = int(request.form["produto_id"])
    quantidade = int(request.form["quantidade"])
    if quantidade <= 0:
        raise ValueError
    return produto_id, quantidade


@vendas_bp.get("/")
def inicio():
    return redirect(url_for("cliente.loja"))


@vendas_bp.get("/painel/vendas")
@permission_required("VENDAS")
def index():
    return render_template("index.html", vendas=listar_vendas(g.usuario["estabelecimento_id"]))


@vendas_bp.get("/painel/relatorio-vendas")
@permission_required("RELATORIOS")
def relatorio():
    hoje = data_hora_loja().date()
    try:
        data_inicio = date.fromisoformat(request.args.get("inicio", hoje.isoformat()))
        data_fim = date.fromisoformat(request.args.get("fim", hoje.isoformat()))
        if data_inicio > data_fim:
            raise ValueError
    except ValueError:
        flash("Escolha um período válido para o relatório.", "danger")
        return redirect(url_for("vendas.relatorio"))
    linhas, resumo = relatorio_vendas(
        g.usuario["estabelecimento_id"], data_inicio.isoformat(), data_fim.isoformat()
    )
    return render_template(
        "relatorio_vendas.html",
        estabelecimento=obter_estabelecimento(g.usuario["estabelecimento_id"]),
        linhas=linhas,
        resumo=resumo,
        data_inicio=data_inicio.isoformat(),
        data_fim=data_fim.isoformat(),
    )


@vendas_bp.route("/vendas/nova", methods=["GET", "POST"])
@permission_required("VENDAS")
def nova_venda():
    if request.method == "GET":
        return render_template("venda.html")
    try:
        cliente = request.form["cliente"].strip()
        produto_id, quantidade = _ler_item_formulario()
        forma = request.form.get("forma_pagamento", "DINHEIRO")
        acao = request.form.get("acao", "ADICIONAR")
        desconto = _valor_monetario(request.form.get("desconto", "0"))
        valor_recebido = _valor_monetario_opcional(request.form.get("valor_recebido"))
        produto = obter_produto(produto_id, g.usuario["estabelecimento_id"])
        if not cliente or produto is None or forma not in FORMAS_PAGAMENTO or acao not in {"ADICIONAR", "COBRAR"} or desconto < 0:
            raise ValueError
    except (KeyError, ValueError, InvalidOperation):
        flash("Preencha mesa ou cliente, produto e quantidade com valores válidos.", "danger")
        return render_template("venda.html"), 400
    try:
        venda = obter_comanda_aberta(cliente, g.usuario["estabelecimento_id"])
        venda_id = venda["id"] if venda is not None else criar_comanda(cliente, g.usuario["estabelecimento_id"])
        venda = adicionar_item_comanda(venda_id, produto_id, quantidade, g.usuario["estabelecimento_id"])
        if acao == "COBRAR":
            venda = preparar_comanda_para_pagamento(
                venda_id, forma, desconto, g.usuario["estabelecimento_id"], valor_recebido
            )
            return _concluir_cobranca(venda)
    except (EstoqueInsuficiente, ValueError) as erro:
        flash(str(erro), "danger")
        return render_template("venda.html"), 400
    flash(f"Item adicionado ao ticket #{venda_id}. A conta continua aberta para novos itens.", "success")
    return redirect(url_for("vendas.comanda", venda_id=venda_id))


@vendas_bp.get("/vendas/<int:venda_id>/comanda")
@permission_required("VENDAS")
def comanda(venda_id):
    venda = obter_venda(venda_id, g.usuario["estabelecimento_id"])
    if venda is None:
        return "Venda não encontrada", 404
    if venda["status_venda"] != "ABERTA":
        return redirect(url_for("vendas.sucesso", venda_id=venda_id))
    return render_template("comanda.html", venda=venda, itens=listar_itens_venda(venda_id))


@vendas_bp.post("/vendas/<int:venda_id>/itens")
@permission_required("VENDAS")
def adicionar_item(venda_id):
    try:
        produto_id, quantidade = _ler_item_formulario()
        if obter_produto(produto_id, g.usuario["estabelecimento_id"]) is None:
            raise ValueError
        adicionar_item_comanda(venda_id, produto_id, quantidade, g.usuario["estabelecimento_id"])
        flash("Item adicionado ao ticket.", "success")
    except (KeyError, ValueError, InvalidOperation, EstoqueInsuficiente) as erro:
        flash(str(erro) or "Não foi possível adicionar este item.", "danger")
    return redirect(url_for("vendas.comanda", venda_id=venda_id))


@vendas_bp.post("/vendas/<int:venda_id>/itens/<int:item_id>/remover")
@permission_required("VENDAS")
def remover_item(venda_id, item_id):
    if remover_item_comanda(venda_id, item_id, g.usuario["estabelecimento_id"]):
        flash("Item removido do ticket.", "success")
    else:
        flash("Não foi possível remover este item. Talvez o ticket já tenha sido fechado.", "warning")
    return redirect(url_for("vendas.comanda", venda_id=venda_id))


@vendas_bp.post("/vendas/<int:venda_id>/fechar")
@permission_required("VENDAS")
def fechar_comanda(venda_id):
    try:
        forma = request.form["forma_pagamento"]
        desconto = _valor_monetario(request.form.get("desconto", "0"))
        valor_recebido = _valor_monetario_opcional(request.form.get("valor_recebido"))
        if forma not in FORMAS_PAGAMENTO:
            raise ValueError
        venda = preparar_comanda_para_pagamento(
            venda_id, forma, desconto, g.usuario["estabelecimento_id"], valor_recebido
        )
        return _concluir_cobranca(venda)
    except (KeyError, ValueError, InvalidOperation, EstoqueInsuficiente) as erro:
        flash(str(erro) or "Confira a forma de pagamento e os itens do ticket.", "danger")
        return redirect(url_for("vendas.comanda", venda_id=venda_id))


@vendas_bp.get("/vendas/<int:venda_id>/sucesso")
@permission_required("VENDAS")
def sucesso(venda_id):
    venda = obter_venda(venda_id, g.usuario["estabelecimento_id"])
    if venda is None:
        return "Venda não encontrada", 404
    if venda["status_venda"] == "ABERTA":
        return redirect(url_for("vendas.comanda", venda_id=venda_id))
    return render_template("sucesso.html", venda=venda, itens=listar_itens_venda(venda_id))


@vendas_bp.get("/vendas/<int:venda_id>/comprovante.pdf")
@permission_required("VENDAS")
def comprovante_pdf(venda_id):
    from nota_pdf import gerar_comprovante_venda_pdf

    venda = obter_venda(venda_id, g.usuario["estabelecimento_id"])
    if venda is None:
        return "Venda não encontrada", 404
    estabelecimento = obter_estabelecimento(g.usuario["estabelecimento_id"])
    arquivo = gerar_comprovante_venda_pdf(venda, estabelecimento, listar_itens_venda(venda_id))
    return send_file(
        BytesIO(arquivo),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"cupom-venda-{venda_id:06d}.pdf",
    )


@vendas_bp.get("/vendas/<int:venda_id>/imprimir")
@permission_required("VENDAS")
def imprimir(venda_id):
    venda = obter_venda(venda_id, g.usuario["estabelecimento_id"])
    if venda is None:
        return "Venda não encontrada", 404
    return render_template(
        "imprimir_venda.html",
        venda=venda,
        itens=listar_itens_venda(venda_id),
        estabelecimento=obter_estabelecimento(g.usuario["estabelecimento_id"]),
    )
