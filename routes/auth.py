from functools import wraps
import re
import sqlite3
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from models import (
    atualizar_configuracao_estabelecimento,
    criar_usuario,
    limpar_tentativas_login,
    listar_funcionarios,
    obter_estabelecimento,
    obter_segredo_webhook_mercadopago,
    obter_token_mercadopago,
    obter_usuario_por_nome,
    quantidade_tentativas_login,
    registrar_tentativa_login,
)

auth_bp = Blueprint("auth", __name__)


def _valor_monetario(texto):
    valor = texto.strip().replace("R$", "").replace(" ", "")
    if "," in valor:
        valor = valor.replace(".", "").replace(",", ".")
    return float(valor)


@auth_bp.before_app_request
def carregar_usuario():
    g.usuario = None
    usuario_id = session.get("usuario_id")
    if usuario_id:
        from database import get_db
        g.usuario = get_db().execute(
            "SELECT id, nome, usuario, papel, estabelecimento_id FROM usuarios WHERE id = ? AND ativo = 1", (usuario_id,)
        ).fetchone()
        if g.usuario is None:
            session.clear()


def login_required(view):
    @wraps(view)
    def protegido(*args, **kwargs):
        if g.usuario is None:
            flash("Entre no painel para continuar.", "warning")
            return redirect(url_for("auth.entrar", proximo=request.path))
        return view(*args, **kwargs)
    return protegido


def owner_required(view):
    @wraps(view)
    def protegido(*args, **kwargs):
        if g.usuario is None:
            flash("Entre no painel para continuar.", "warning")
            return redirect(url_for("auth.entrar", proximo=request.path))
        if g.usuario["papel"] != "DONO":
            flash("Apenas o dono pode acessar esta area.", "danger")
            return redirect(url_for("vendas.index"))
        return view(*args, **kwargs)
    return protegido


@auth_bp.route("/entrar", methods=["GET", "POST"])
def entrar():
    if g.usuario is not None:
        return redirect(url_for("vendas.index"))
    if request.method == "POST":
        endereco_ip = request.remote_addr or "desconhecido"
        if quantidade_tentativas_login(
            endereco_ip, current_app.config["LOGIN_JANELA_SEGUNDOS"]
        ) >= current_app.config["LOGIN_MAX_TENTATIVAS"]:
            flash("Muitas tentativas de acesso. Aguarde alguns minutos e tente novamente.", "danger")
            return render_template("entrar.html", proximo=request.form.get("proximo", "")), 429
        usuario = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")
        conta = obter_usuario_por_nome(usuario)
        if conta and check_password_hash(conta["senha_hash"], senha):
            limpar_tentativas_login(endereco_ip)
            session.clear()
            session["usuario_id"] = conta["id"]
            proximo = request.form.get("proximo", "")
            if not proximo.startswith("/") or proximo.startswith("//"):
                proximo = url_for("vendas.index")
            return redirect(proximo)
        registrar_tentativa_login(endereco_ip)
        flash("Usuario ou senha invalidos.", "danger")
    return render_template("entrar.html", proximo=request.args.get("proximo", ""))


@auth_bp.post("/sair")
def sair():
    session.clear()
    flash("Sessao encerrada.", "success")
    return redirect(url_for("cliente.loja"))


@auth_bp.get("/usuarios")
@owner_required
def usuarios():
    return render_template("usuarios.html", usuarios=listar_funcionarios(g.usuario["estabelecimento_id"]))


@auth_bp.route("/configuracoes", methods=["GET", "POST"])
@owner_required
def configuracoes():
    estabelecimento = obter_estabelecimento(g.usuario["estabelecimento_id"])
    if estabelecimento is None:
        return "Estabelecimento nao encontrado", 404
    if request.method == "POST":
        try:
            nome = request.form.get("nome", "").strip()
            whatsapp = "".join(caractere for caractere in request.form.get("whatsapp", "") if caractere.isdigit())
            valor_entrega = _valor_monetario(request.form.get("valor_entrega", ""))
            url_publica = request.form.get("url_publica", "").strip().rstrip("/")
            access_token = request.form.get("mercadopago_access_token", "").strip()
            webhook_secret = request.form.get("mercadopago_webhook_secret", "").strip()
            endereco = urlparse(url_publica)
            if (
                not 2 <= len(nome) <= 120
                or not 10 <= len(whatsapp) <= 15
                or not 0 <= valor_entrega <= 1_000
                or endereco.scheme != "https"
                or not endereco.hostname
                or len(access_token) > 500
                or len(webhook_secret) > 500
            ):
                raise ValueError
            atualizar_configuracao_estabelecimento(
                estabelecimento["id"], nome, whatsapp, valor_entrega, url_publica, access_token, webhook_secret
            )
            flash("Configuracoes salvas. O novo frete ja aparece no carrinho e no pagamento.", "success")
            return redirect(url_for("auth.configuracoes"))
        except (TypeError, ValueError):
            flash("Confira nome, WhatsApp, URL HTTPS e valor de entrega.", "danger")
    estabelecimento = obter_estabelecimento(estabelecimento["id"])
    return render_template(
        "configuracoes.html",
        estabelecimento=estabelecimento,
        url_publica=estabelecimento["url_publica"] or current_app.config["BASE_URL"],
        token_configurado=bool(obter_token_mercadopago(estabelecimento["id"])),
        webhook_configurado=bool(obter_segredo_webhook_mercadopago(estabelecimento["id"])),
    )


@auth_bp.route("/usuarios/novo", methods=["GET", "POST"])
@owner_required
def novo_usuario():
    if request.method == "GET":
        return render_template("usuario.html")
    try:
        nome = request.form["nome"].strip()
        usuario = request.form["usuario"].strip()
        senha = request.form["senha"]
        if not nome or not re.fullmatch(r"[A-Za-z0-9_.-]{3,50}", usuario) or len(senha) < 12:
            raise ValueError
        criar_usuario(nome, usuario, generate_password_hash(senha), "FUNCIONARIO", g.usuario["estabelecimento_id"])
    except (KeyError, ValueError):
        flash("Informe nome, usuario valido e uma senha com pelo menos 12 caracteres.", "danger")
        return render_template("usuario.html"), 400
    except sqlite3.IntegrityError:
        flash("Este nome de usuario ja esta em uso.", "danger")
        return render_template("usuario.html"), 400
    flash("Funcionario cadastrado com sucesso.", "success")
    return redirect(url_for("auth.usuarios"))
