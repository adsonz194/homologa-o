from decimal import Decimal, InvalidOperation
import re
import sqlite3
from urllib.parse import parse_qs, urlencode, urlparse

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from models import (
    atualizar_produto,
    buscar_produtos,
    criar_produto,
    listar_complementos_produto,
    listar_produtos,
    obter_produto,
    registrar_auditoria,
    substituir_complementos_produto,
)
from routes.auth import permission_required

produtos_bp = Blueprint("produtos", __name__)
HOSTS_GOOGLE_DRIVE = {"drive.google.com", "www.drive.google.com"}


def normalizar_url_imagem(imagem_url):
    """Transforma links publicos de arquivo do Drive em URL de miniatura.

    O link de compartilhamento comum do Drive abre uma pagina HTML, nao uma
    imagem. A URL /thumbnail e apropriada para ser usada diretamente na tag
    img do cardapio, sem baixar o arquivo para o servidor da loja.
    """
    if not imagem_url:
        return ""
    url = urlparse(imagem_url)
    if url.scheme != "https" or not url.netloc or len(imagem_url) > 500:
        raise ValueError
    if url.hostname.lower() not in HOSTS_GOOGLE_DRIVE:
        return imagem_url

    parametros = parse_qs(url.query)
    correspondencia = re.search(r"/file/d/([A-Za-z0-9_-]+)", url.path)
    arquivo_id = (correspondencia.group(1) if correspondencia else (parametros.get("id") or [""])[0])
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", arquivo_id):
        raise ValueError
    consulta = {"id": arquivo_id, "sz": "w1200"}
    # Alguns links recentes do Drive incluem resourcekey; preserva-o para que
    # a imagem continue acessivel para quem recebeu o link publico.
    resource_key = (parametros.get("resourcekey") or [""])[0]
    if resource_key:
        consulta["resourcekey"] = resource_key
    return f"https://drive.google.com/thumbnail?{urlencode(consulta)}"


def dados_produto_do_formulario():
    codigo_interno = request.form["codigo_interno"].strip()
    ean = request.form.get("ean", "").strip()
    descricao = request.form["descricao"].strip()
    valor_unitario = float(Decimal(request.form["valor_unitario"].replace(",", ".")))
    estoque = int(request.form["estoque"])
    disponivel = request.form.get("disponivel") == "on"
    categoria = " ".join(request.form.get("categoria", "Geral").split()) or "Geral"
    imagem_url = normalizar_url_imagem(request.form.get("imagem_url", "").strip())
    if (
        not codigo_interno or not descricao or (ean and not ean.isdigit())
        or valor_unitario <= 0 or estoque < 0 or not 1 <= len(categoria) <= 60
    ):
        raise ValueError
    return codigo_interno, ean, descricao, valor_unitario, estoque, disponivel, categoria, imagem_url


def dados_complementos_do_formulario():
    descricoes = request.form.getlist("complemento_descricao")
    valores = request.form.getlist("complemento_valor")
    if len(descricoes) != len(valores):
        raise ValueError
    complementos = []
    nomes = set()
    for descricao, valor in zip(descricoes, valores):
        descricao = descricao.strip()
        # Uma linha vazia e ignorada para tornar o cadastro mais pratico.
        if not descricao and not valor.strip():
            continue
        valor_adicional = float(Decimal((valor or "0").replace(",", ".")))
        nome_normalizado = descricao.casefold()
        if (
            not 1 <= len(descricao) <= 100
            or valor_adicional < 0
            or valor_adicional > 10000
            or nome_normalizado in nomes
        ):
            raise ValueError
        nomes.add(nome_normalizado)
        complementos.append({"descricao": descricao, "valor_adicional": valor_adicional})
    return complementos


@produtos_bp.get("/produtos")
@permission_required("PRODUTOS")
def index():
    return render_template("produtos.html", produtos=listar_produtos(g.usuario["estabelecimento_id"]))


@produtos_bp.route("/produtos/novo", methods=["GET", "POST"])
@permission_required("PRODUTOS")
def novo():
    if request.method == "GET":
        return render_template("produto.html", produto=None, complementos=[])
    try:
        complementos = dados_complementos_do_formulario()
        produto_id = criar_produto(*dados_produto_do_formulario(), g.usuario["estabelecimento_id"])
        substituir_complementos_produto(produto_id, complementos)
        registrar_auditoria(g.usuario["estabelecimento_id"], g.usuario, "Cadastrou produto", "PRODUTO", produto_id)
    except (KeyError, ValueError, InvalidOperation):
        flash("Confira os dados do produto e dos complementos.", "danger")
        return render_template("produto.html", produto=None, complementos=[]), 400
    except sqlite3.IntegrityError:
        flash("O codigo interno ou EAN ja esta cadastrado.", "danger")
        return render_template("produto.html", produto=None, complementos=[]), 400
    flash("Produto cadastrado com sucesso.", "success")
    return redirect(url_for("produtos.index"))


@produtos_bp.route("/produtos/<int:produto_id>/editar", methods=["GET", "POST"])
@permission_required("PRODUTOS")
def editar(produto_id):
    produto = obter_produto(produto_id, g.usuario["estabelecimento_id"])
    if produto is None:
        return "Produto nao encontrado", 404
    if request.method == "GET":
        return render_template("produto.html", produto=produto, complementos=listar_complementos_produto(produto_id, somente_ativos=False))
    try:
        complementos = dados_complementos_do_formulario()
        atualizar_produto(produto_id, *dados_produto_do_formulario(), g.usuario["estabelecimento_id"])
        substituir_complementos_produto(produto_id, complementos)
        registrar_auditoria(g.usuario["estabelecimento_id"], g.usuario, "Atualizou produto", "PRODUTO", produto_id)
    except (KeyError, ValueError, InvalidOperation):
        flash("Confira os dados do produto e dos complementos.", "danger")
        return render_template("produto.html", produto=produto, complementos=listar_complementos_produto(produto_id, somente_ativos=False)), 400
    except sqlite3.IntegrityError:
        flash("O codigo interno ou EAN ja esta cadastrado.", "danger")
        return render_template("produto.html", produto=produto, complementos=listar_complementos_produto(produto_id, somente_ativos=False)), 400
    flash("Produto atualizado.", "success")
    return redirect(url_for("produtos.index"))


@produtos_bp.get("/api/produtos/buscar")
@permission_required("PRODUTOS")
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
