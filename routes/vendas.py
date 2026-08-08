from datetime import date
from decimal import Decimal, InvalidOperation
from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from routes.auth import permission_required
from models import (
    EstoqueInsuficiente, criar_venda, data_hora_loja, listar_vendas,
    obter_estabelecimento, obter_produto, obter_venda, relatorio_vendas,
)

vendas_bp = Blueprint("vendas", __name__)
FORMAS_PAGAMENTO = {"PIX", "CREDITO", "DEBITO"}

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
        produto_id = int(request.form["produto_id"])
        produto = obter_produto(produto_id, g.usuario["estabelecimento_id"])
        if produto is None:
            raise ValueError
        quantidade = int(request.form["quantidade"])
        valor = float(produto["valor_unitario"])
        desconto = float(Decimal(request.form.get("desconto", "0").replace(",", ".")))
        forma = request.form["forma_pagamento"]
        if (
            not cliente or quantidade <= 0 or valor <= 0 or desconto < 0
            or desconto >= quantidade * valor or forma not in FORMAS_PAGAMENTO
        ):
            raise ValueError
    except (KeyError, ValueError, InvalidOperation):
        flash("Preencha valores válidos: o preço deve ser maior que zero e o desconto menor que o total.", "danger")
        return render_template("venda.html"), 400
    try:
        venda_id = criar_venda(cliente, produto["descricao"], quantidade, valor, desconto, forma, produto_id, estabelecimento_id=g.usuario["estabelecimento_id"])
    except EstoqueInsuficiente as erro:
        flash(str(erro), "danger")
        return render_template("venda.html"), 400
    return render_template(
        "iniciar_pagamento.html",
        destino=url_for("pagamentos.criar_checkout", venda_id=venda_id),
        titulo="Preparando o checkout",
        descricao="Abrindo o ambiente seguro do Mercado Pago.",
        auto_submit=True,
    )

@vendas_bp.get("/vendas/<int:venda_id>/sucesso")
@permission_required("VENDAS")
def sucesso(venda_id):
    venda = obter_venda(venda_id, g.usuario["estabelecimento_id"])
    if venda is None: return "Venda não encontrada", 404
    return render_template("sucesso.html", venda=venda)
