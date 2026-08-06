from decimal import Decimal, InvalidOperation
import sqlite3

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from models import atualizar_produto, buscar_produtos, criar_produto, listar_produtos, obter_produto
from routes.auth import login_required, owner_required

produtos_bp = Blueprint("produtos", __name__)


def dados_produto_do_formulario():
    codigo_interno = request.form["codigo_interno"].strip()
    ean = request.form.get("ean", "").strip()
    descricao = request.form["descricao"].strip()
    valor_unitario = float(Decimal(request.form["valor_unitario"].replace(",", ".")))
    estoque = int(request.form["estoque"])
    disponivel = request.form.get("disponivel") == "on"
    if not codigo_interno or not descricao or (ean and not ean.isdigit()) or valor_unitario <= 0 or estoque < 0:
        raise ValueError
    return codigo_interno, ean, descricao, valor_unitario, estoque, disponivel


@produtos_bp.get("/produtos")
@owner_required
def index():
    return render_template("produtos.html", produtos=listar_produtos(g.usuario["estabelecimento_id"]))


@produtos_bp.route("/produtos/novo", methods=["GET", "POST"])
@owner_required
def novo():
    if request.method == "GET":
        return render_template("produto.html", produto=None)
    try:
        criar_produto(*dados_produto_do_formulario(), g.usuario["estabelecimento_id"])
    except (KeyError, ValueError, InvalidOperation):
        flash("Informe codigo, descricao, valor e estoque validos.", "danger")
        return render_template("produto.html", produto=None), 400
    except sqlite3.IntegrityError:
        flash("O codigo interno ou EAN ja esta cadastrado.", "danger")
        return render_template("produto.html", produto=None), 400
    flash("Produto cadastrado com sucesso.", "success")
    return redirect(url_for("produtos.index"))


@produtos_bp.route("/produtos/<int:produto_id>/editar", methods=["GET", "POST"])
@owner_required
def editar(produto_id):
    produto = obter_produto(produto_id, g.usuario["estabelecimento_id"])
    if produto is None:
        return "Produto nao encontrado", 404
    if request.method == "GET":
        return render_template("produto.html", produto=produto)
    try:
        atualizar_produto(produto_id, *dados_produto_do_formulario(), g.usuario["estabelecimento_id"])
    except (KeyError, ValueError, InvalidOperation):
        flash("Informe codigo, descricao, valor e estoque validos.", "danger")
        return render_template("produto.html", produto=produto), 400
    except sqlite3.IntegrityError:
        flash("O codigo interno ou EAN ja esta cadastrado.", "danger")
        return render_template("produto.html", produto=produto), 400
    flash("Produto atualizado.", "success")
    return redirect(url_for("produtos.index"))


@produtos_bp.get("/api/produtos/buscar")
@login_required
def buscar():
    consulta = request.args.get("q", "").strip()
    if not consulta:
        return jsonify([])
    produtos = buscar_produtos(consulta, g.usuario["estabelecimento_id"])
    return jsonify([{
        "id": produto["id"],
        "codigo_interno": produto["codigo_interno"],
        "ean": produto["ean"],
        "descricao": produto["descricao"],
        "valor_unitario": produto["valor_unitario"],
        "estoque": produto["estoque"],
    } for produto in produtos])
