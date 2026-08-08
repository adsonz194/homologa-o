from datetime import datetime
from functools import wraps
import re
import sqlite3
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from models import (
    atualizar_configuracao_estabelecimento,
    atualizar_funcionario,
    criar_usuario,
    definir_usuario_ativo,
    definir_fechado_hoje,
    limpar_tentativas_login,
    listar_funcionarios,
    obter_estabelecimento,
    obter_funcionario,
    obter_segredo_webhook_mercadopago,
    obter_token_mercadopago,
    obter_usuario_por_nome,
    quantidade_tentativas_login,
    registrar_tentativa_login,
    status_funcionamento_estabelecimento,
)

auth_bp = Blueprint("auth", __name__)
PERMISSOES_FUNCIONARIO = (
    ("PEDIDOS", "Acompanhar e atualizar pedidos"),
    ("PRODUTOS", "Cadastrar e editar itens do cardapio"),
    ("VENDAS", "Registrar vendas no balcao"),
    ("RELATORIOS", "Consultar e imprimir relatorios de vendas"),
)
CODIGOS_PERMISSOES_FUNCIONARIO = {codigo for codigo, _ in PERMISSOES_FUNCIONARIO}
DIAS_FUNCIONAMENTO = (
    ("0", "Seg"), ("1", "Ter"), ("2", "Qua"), ("3", "Qui"),
    ("4", "Sex"), ("5", "Sáb"), ("6", "Dom"),
)


def _valor_monetario(texto):
    valor = texto.strip().replace("R$", "").replace(" ", "")
    if "," in valor:
        valor = valor.replace(".", "").replace(",", ".")
    return float(valor)


def _horario_valido(texto):
    return datetime.strptime(texto, "%H:%M").strftime("%H:%M")


def _cnpj_valido(cnpj):
    if not cnpj:
        return True
    if len(cnpj) != 14 or len(set(cnpj)) == 1:
        return False
    pesos = ((5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2), (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    digitos = [int(caractere) for caractere in cnpj]
    for indice, peso in enumerate(pesos):
        soma = sum(numero * multiplicador for numero, multiplicador in zip(digitos[:12 + indice], peso))
        esperado = 11 - (soma % 11)
        if esperado >= 10:
            esperado = 0
        if digitos[12 + indice] != esperado:
            return False
    return True


def permissoes_usuario(usuario=None):
    usuario = usuario or g.usuario
    if usuario is None or usuario["papel"] == "DONO":
        return set()
    return {
        permissao for permissao in str(usuario["permissoes"] or "").split(",")
        if permissao in CODIGOS_PERMISSOES_FUNCIONARIO
    }


def usuario_tem_permissao(permissao, usuario=None):
    usuario = usuario or g.usuario
    return usuario is not None and (
        usuario["papel"] == "DONO" or permissao in permissoes_usuario(usuario)
    )


def rota_inicial_painel(usuario=None):
    usuario = usuario or g.usuario
    if usuario is None:
        return url_for("cliente.loja")
    if usuario["papel"] == "DONO":
        return url_for("vendas.index")
    permissoes = permissoes_usuario(usuario)
    if "PEDIDOS" in permissoes:
        return url_for("pedidos.index")
    if "PRODUTOS" in permissoes:
        return url_for("produtos.index")
    if "VENDAS" in permissoes:
        return url_for("vendas.nova_venda")
    if "RELATORIOS" in permissoes:
        return url_for("vendas.relatorio")
    return url_for("cliente.loja")


@auth_bp.before_app_request
def carregar_usuario():
    g.usuario = None
    usuario_id = session.get("usuario_id")
    if usuario_id:
        from database import get_db
        g.usuario = get_db().execute(
            "SELECT id, nome, usuario, papel, permissoes, estabelecimento_id FROM usuarios WHERE id = ? AND ativo = 1", (usuario_id,)
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
            return redirect(rota_inicial_painel())
        return view(*args, **kwargs)
    return protegido


def permission_required(permissao):
    """Permite ao dono tudo e ao funcionario somente o que foi concedido."""
    def decorador(view):
        @wraps(view)
        def protegido(*args, **kwargs):
            if g.usuario is None:
                flash("Entre no painel para continuar.", "warning")
                return redirect(url_for("auth.entrar", proximo=request.path))
            if not usuario_tem_permissao(permissao):
                flash("Seu usuario nao tem permissao para esta funcao.", "danger")
                return redirect(rota_inicial_painel())
            return view(*args, **kwargs)
        return protegido
    return decorador


@auth_bp.route("/entrar", methods=["GET", "POST"])
def entrar():
    if g.usuario is not None:
        return redirect(rota_inicial_painel())
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
                proximo = rota_inicial_painel(conta)
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


@auth_bp.post("/usuarios/<int:usuario_id>/acesso")
@owner_required
def alterar_acesso_usuario(usuario_id):
    ativo = request.form.get("acao") == "reativar"
    if not definir_usuario_ativo(usuario_id, g.usuario["estabelecimento_id"], ativo):
        return "Funcionario nao encontrado", 404
    flash("Funcionario reativado." if ativo else "Funcionario desativado e sem acesso ao painel.", "success")
    return redirect(url_for("auth.usuarios"))


@auth_bp.route("/usuarios/<int:usuario_id>/editar", methods=["GET", "POST"])
@owner_required
def editar_usuario(usuario_id):
    funcionario = obter_funcionario(usuario_id, g.usuario["estabelecimento_id"])
    if funcionario is None:
        return "Funcionario nao encontrado", 404
    if request.method == "GET":
        return render_template(
            "editar_usuario.html", funcionario=funcionario,
            permissoes_disponiveis=PERMISSOES_FUNCIONARIO,
            permissoes_selecionadas=permissoes_usuario(funcionario),
        )
    try:
        nome = request.form["nome"].strip()
        usuario = request.form["usuario"].strip()
        senha = request.form.get("senha", "")
        permissoes = sorted({
            permissao for permissao in request.form.getlist("permissoes")
            if permissao in CODIGOS_PERMISSOES_FUNCIONARIO
        })
        if not nome or not re.fullmatch(r"[A-Za-z0-9_.-]{3,50}", usuario) or (senha and len(senha) < 12):
            raise ValueError
        senha_hash = generate_password_hash(senha) if senha else None
        if not atualizar_funcionario(
            funcionario["id"], g.usuario["estabelecimento_id"], nome, usuario,
            ",".join(permissoes), senha_hash,
        ):
            return "Funcionario nao encontrado", 404
    except (KeyError, ValueError):
        flash("Confira nome, usuario e senha. A senha, se alterada, precisa ter ao menos 12 caracteres.", "danger")
        return render_template(
            "editar_usuario.html", funcionario=funcionario,
            permissoes_disponiveis=PERMISSOES_FUNCIONARIO,
            permissoes_selecionadas=set(request.form.getlist("permissoes")),
        ), 400
    except sqlite3.IntegrityError:
        flash("Este nome de usuario ja esta em uso.", "danger")
        return render_template(
            "editar_usuario.html", funcionario=funcionario,
            permissoes_disponiveis=PERMISSOES_FUNCIONARIO,
            permissoes_selecionadas=set(request.form.getlist("permissoes")),
        ), 400
    flash("Funcionario atualizado com sucesso.", "success")
    return redirect(url_for("auth.usuarios"))


@auth_bp.route("/configuracoes", methods=["GET", "POST"])
@owner_required
def configuracoes():
    estabelecimento = obter_estabelecimento(g.usuario["estabelecimento_id"])
    if estabelecimento is None:
        return "Estabelecimento nao encontrado", 404
    if request.method == "POST":
        try:
            nome = request.form.get("nome", "").strip()
            razao_social = request.form.get("razao_social", "").strip() or nome
            cnpj = "".join(caractere for caractere in request.form.get("cnpj", "") if caractere.isdigit())
            endereco_loja = request.form.get("endereco_loja", "").strip()
            telefone = "".join(caractere for caractere in request.form.get("telefone", "") if caractere.isdigit())
            whatsapp = "".join(caractere for caractere in request.form.get("whatsapp", "") if caractere.isdigit())
            valor_entrega = _valor_monetario(request.form.get("valor_entrega", ""))
            url_publica = request.form.get("url_publica", "").strip().rstrip("/")
            dias = sorted({dia for dia in request.form.getlist("dias_funcionamento") if dia in {str(numero) for numero, _ in DIAS_FUNCIONAMENTO}}, key=int)
            horario_abertura = _horario_valido(request.form.get("horario_abertura", ""))
            horario_encerramento = _horario_valido(request.form.get("horario_encerramento", ""))
            access_token = request.form.get("mercadopago_access_token", "").strip()
            webhook_secret = request.form.get("mercadopago_webhook_secret", "").strip()
            endereco = urlparse(url_publica)
            if (
                not 2 <= len(nome) <= 120
                or not 2 <= len(razao_social) <= 150
                or not _cnpj_valido(cnpj)
                or len(endereco_loja) > 250
                or (telefone and not 10 <= len(telefone) <= 15)
                or not 10 <= len(whatsapp) <= 15
                or not 0 <= valor_entrega <= 1_000
                or endereco.scheme != "https"
                or not endereco.hostname
                or not dias
                or horario_abertura == horario_encerramento
                or (horario_encerramento != "00:00" and horario_abertura > horario_encerramento)
                or len(access_token) > 500
                or len(webhook_secret) > 500
            ):
                raise ValueError
            atualizar_configuracao_estabelecimento(
                estabelecimento["id"], nome, razao_social, cnpj, endereco_loja, telefone, whatsapp, valor_entrega, url_publica,
                ",".join(dias), horario_abertura, horario_encerramento, access_token, webhook_secret,
            )
            flash("Configurações salvas. Horários, dias e frete já aparecem no delivery.", "success")
            return redirect(url_for("auth.configuracoes"))
        except (TypeError, ValueError):
            flash("Confira nome, WhatsApp, URL HTTPS, dias e horários de funcionamento.", "danger")
    estabelecimento = obter_estabelecimento(estabelecimento["id"])
    return render_template(
        "configuracoes.html",
        estabelecimento=estabelecimento,
        url_publica=estabelecimento["url_publica"] or current_app.config["BASE_URL"],
        token_configurado=bool(obter_token_mercadopago(estabelecimento["id"])),
        webhook_configurado=bool(obter_segredo_webhook_mercadopago(estabelecimento["id"])),
        dias_funcionamento=DIAS_FUNCIONAMENTO,
        dias_selecionados=set(str(estabelecimento["dias_funcionamento"] or "").split(",")),
        funcionamento=status_funcionamento_estabelecimento(estabelecimento),
    )


@auth_bp.post("/configuracoes/fechado-hoje")
@owner_required
def alternar_fechado_hoje():
    estabelecimento = obter_estabelecimento(g.usuario["estabelecimento_id"])
    if estabelecimento is None:
        return "Estabelecimento nao encontrado", 404
    fechar = request.form.get("acao") == "fechar"
    definir_fechado_hoje(estabelecimento["id"], fechar)
    flash("Delivery fechado hoje." if fechar else "Delivery reaberto para hoje.", "success")
    return redirect(url_for("auth.configuracoes"))


@auth_bp.route("/usuarios/novo", methods=["GET", "POST"])
@owner_required
def novo_usuario():
    if request.method == "GET":
        return render_template("usuario.html", permissoes_disponiveis=PERMISSOES_FUNCIONARIO, permissoes_selecionadas=set())
    try:
        nome = request.form["nome"].strip()
        usuario = request.form["usuario"].strip()
        senha = request.form["senha"]
        permissoes = sorted({
            permissao for permissao in request.form.getlist("permissoes")
            if permissao in CODIGOS_PERMISSOES_FUNCIONARIO
        })
        if not nome or not re.fullmatch(r"[A-Za-z0-9_.-]{3,50}", usuario) or len(senha) < 12:
            raise ValueError
        criar_usuario(
            nome, usuario, generate_password_hash(senha), "FUNCIONARIO",
            g.usuario["estabelecimento_id"], ",".join(permissoes),
        )
    except (KeyError, ValueError):
        flash("Informe nome, usuario valido e uma senha com pelo menos 12 caracteres.", "danger")
        return render_template("usuario.html", permissoes_disponiveis=PERMISSOES_FUNCIONARIO, permissoes_selecionadas=set(request.form.getlist("permissoes"))), 400
    except sqlite3.IntegrityError:
        flash("Este nome de usuario ja esta em uso.", "danger")
        return render_template("usuario.html", permissoes_disponiveis=PERMISSOES_FUNCIONARIO, permissoes_selecionadas=set(request.form.getlist("permissoes"))), 400
    flash("Funcionario cadastrado com as permissoes selecionadas.", "success")
    return redirect(url_for("auth.usuarios"))
