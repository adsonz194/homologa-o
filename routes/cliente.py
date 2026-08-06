from io import BytesIO

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, session, url_for

from models import (
    EstoqueInsuficiente,
    criar_pedido,
    detalhes_carrinho,
    itens_pedido,
    listar_produtos_disponiveis,
    obter_estabelecimento,
    obter_estabelecimento_por_slug,
    obter_url_publica_estabelecimento,
    obter_whatsapp_estabelecimento,
    obter_pedido,
    obter_pedido_por_codigo,
    obter_produto,
)
from nota_pdf import gerar_comprovante_pedido_pdf

cliente_bp = Blueprint("cliente", __name__)
FORMAS_PAGAMENTO = {"PIX", "CREDITO", "DEBITO"}
STATUS_OPERACIONAL_NOMES = {
    "PENDENTE": "Aguardando confirmacao do pagamento",
    "FILA_DE_ESPERA": "Na fila de espera",
    "PREPARANDO": "Em preparacao",
    "PRONTO": "Pronto para entrega",
    "SAIU_PARA_ENTREGA": "Saiu para entrega",
    "ENTREGUE": "Entregue",
    "CANCELADO": "Cancelado",
    "EXTRAVIADO": "Pedido extraviado",
}


def carrinho_atual():
    carrinho = session.get("carrinho", {})
    return carrinho if isinstance(carrinho, dict) else {}


def salvar_carrinho(carrinho):
    session["carrinho"] = carrinho
    session.modified = True


def estabelecimento_principal():
    """A aplicacao voltou a operar somente o delivery principal."""
    return obter_estabelecimento_por_slug(current_app.config["ESTABELECIMENTO_PADRAO_SLUG"])


def renderizar_loja():
    estabelecimento = estabelecimento_principal()
    if estabelecimento is None:
        return "Delivery indisponivel", 503
    session["estabelecimento_publico_id"] = estabelecimento["id"]
    return render_template(
        "cliente.html",
        produtos=listar_produtos_disponiveis(estabelecimento["id"]),
        quantidade_carrinho=sum(carrinho_atual().values()),
        estabelecimento=estabelecimento,
    )


@cliente_bp.get("/cliente")
def loja():
    return renderizar_loja()


@cliente_bp.post("/cliente/carrinho/adicionar/<int:produto_id>")
def adicionar_ao_carrinho(produto_id):
    estabelecimento = estabelecimento_principal()
    if estabelecimento is None:
        return "Delivery indisponivel", 503
    try:
        quantidade = int(request.form.get("quantidade", 1))
        if quantidade <= 0:
            raise ValueError
    except ValueError:
        flash("Quantidade invalida.", "danger")
        return redirect(url_for("cliente.loja"))
    produto = obter_produto(produto_id, estabelecimento["id"])
    if produto is None or not produto["disponivel"] or produto["estoque"] <= 0:
        flash("Este produto nao esta mais disponivel.", "warning")
        return redirect(url_for("cliente.loja"))
    carrinho = carrinho_atual()
    chave = str(produto_id)
    quantidade_no_carrinho = int(carrinho.get(chave, 0))
    if quantidade + quantidade_no_carrinho > produto["estoque"]:
        flash(f"Ha apenas {produto['estoque']} unidade(s) disponivel(is) deste produto.", "warning")
        return redirect(url_for("cliente.loja"))
    carrinho[chave] = quantidade_no_carrinho + quantidade
    salvar_carrinho(carrinho)
    flash("Produto adicionado ao carrinho.", "success")
    return redirect(url_for("cliente.loja"))


@cliente_bp.get("/cliente/carrinho")
def carrinho():
    estabelecimento = estabelecimento_principal()
    if estabelecimento is None:
        return "Delivery indisponivel", 503
    itens = detalhes_carrinho(carrinho_atual(), estabelecimento["id"])
    subtotal = sum(item["subtotal"] for item in itens)
    total = subtotal + estabelecimento["valor_entrega"] if itens else subtotal
    return render_template(
        "carrinho.html", itens=itens, subtotal=subtotal, total=total, estabelecimento=estabelecimento
    )


@cliente_bp.post("/cliente/carrinho/atualizar/<int:produto_id>")
def atualizar_carrinho(produto_id):
    estabelecimento = estabelecimento_principal()
    if estabelecimento is None:
        return "Delivery indisponivel", 503
    carrinho = carrinho_atual()
    try:
        quantidade = int(request.form["quantidade"])
    except (KeyError, ValueError):
        flash("Quantidade invalida.", "danger")
        return redirect(url_for("cliente.carrinho"))
    chave = str(produto_id)
    produto = obter_produto(produto_id, estabelecimento["id"])
    if produto is None or not produto["disponivel"]:
        carrinho.pop(chave, None)
        salvar_carrinho(carrinho)
        flash("Produto indisponivel removido do carrinho.", "warning")
        return redirect(url_for("cliente.carrinho"))
    if quantidade > produto["estoque"]:
        flash(f"Ha apenas {produto['estoque']} unidade(s) disponivel(is) deste produto.", "warning")
        return redirect(url_for("cliente.carrinho"))
    if quantidade <= 0:
        carrinho.pop(chave, None)
    else:
        carrinho[chave] = quantidade
    salvar_carrinho(carrinho)
    return redirect(url_for("cliente.carrinho"))


@cliente_bp.route("/cliente/finalizar", methods=["GET", "POST"])
def finalizar():
    estabelecimento = estabelecimento_principal()
    if estabelecimento is None:
        return "Delivery indisponivel", 503
    itens = detalhes_carrinho(carrinho_atual(), estabelecimento["id"])
    if not itens:
        flash("Seu carrinho esta vazio.", "warning")
        return redirect(url_for("cliente.loja"))
    total = sum(item["subtotal"] for item in itens) + estabelecimento["valor_entrega"]
    if request.method == "GET":
        return render_template("finalizar.html", itens=itens, total=total, estabelecimento=estabelecimento)
    cliente = request.form.get("cliente", "").strip()
    telefone = request.form.get("telefone", "").strip()
    endereco = request.form.get("endereco", "").strip()
    forma_pagamento = request.form.get("forma_pagamento", "")
    telefone_numeros = "".join(caractere for caractere in telefone if caractere.isdigit())
    if (
        not 2 <= len(cliente) <= 100
        or not 8 <= len(telefone_numeros) <= 15
        or not 8 <= len(endereco) <= 300
        or forma_pagamento not in FORMAS_PAGAMENTO
    ):
        flash("Confira nome, telefone, endereco e forma de pagamento.", "danger")
        return render_template("finalizar.html", itens=itens, total=total, estabelecimento=estabelecimento), 400
    try:
        pedido_id = criar_pedido(
            cliente, telefone, endereco, "", forma_pagamento, carrinho_atual(), estabelecimento["id"]
        )
    except EstoqueInsuficiente as erro:
        flash(str(erro), "danger")
        return redirect(url_for("cliente.carrinho"))
    session.pop("carrinho", None)
    session["pedido_pagamento_pendente"] = pedido_id
    # A preferencia e criada na propria resposta ao clique do cliente. Isso
    # evita que Safari/iOS bloqueie um redirecionamento externo iniciado por
    # JavaScript em uma pagina intermediaria.
    from routes.pagamentos import criar_checkout_pedido
    return criar_checkout_pedido(pedido_id)


@cliente_bp.get("/cliente/pagamento/<int:pedido_id>/iniciar")
def iniciar_pagamento(pedido_id):
    if session.get("pedido_pagamento_pendente") != pedido_id:
        flash("Para sua seguranca, inicie o pagamento a partir do seu carrinho ou codigo de acompanhamento.", "warning")
        return redirect(url_for("cliente.loja"))
    pedido_atual = obter_pedido(pedido_id)
    if pedido_atual is None or pedido_atual["status_pagamento"] != "PENDENTE":
        flash("Este pedido nao esta disponivel para um novo pagamento.", "warning")
        return redirect(url_for("cliente.loja"))
    from routes.pagamentos import criar_autorizacao_pagamento
    return render_template(
        "iniciar_pagamento.html",
        destino=url_for("pagamentos.criar_checkout_pedido", pedido_id=pedido_id),
        titulo="Preparando o pagamento",
        descricao="Voce sera direcionado ao ambiente seguro do Mercado Pago.",
        autorizacao_pagamento=criar_autorizacao_pagamento(pedido_atual),
        auto_submit=True,
    )


def renderizar_pedido(pedido_atual, retorno_checkout=False):
    codigo = pedido_atual["codigo_acompanhamento"]
    return render_template(
        "pedido.html",
        pedido=pedido_atual,
        codigo_acompanhamento=codigo,
        nome_status_operacional=STATUS_OPERACIONAL_NOMES.get(pedido_atual["status_operacional"], "Em atualizacao"),
        url_status=url_for("cliente.status_pedido", codigo=codigo),
        url_acompanhamento=(
            f"{obter_url_publica_estabelecimento(pedido_atual['estabelecimento_id'])}"
            f"{url_for('cliente.pedido', codigo=codigo)}"
        ),
        url_reiniciar_pagamento=url_for("cliente.reiniciar_pagamento", codigo=codigo),
        url_nota_pdf=url_for("cliente.nota_pdf", codigo=codigo),
        whatsapp_empresa=obter_whatsapp_estabelecimento(pedido_atual["estabelecimento_id"]),
        retorno_checkout=retorno_checkout,
    )


@cliente_bp.get("/cliente/acompanhamento/<codigo>/nota.pdf")
def nota_pdf(codigo):
    pedido_atual = obter_pedido_por_codigo(codigo)
    if pedido_atual is None:
        return "Pedido nao encontrado", 404
    estabelecimento = obter_estabelecimento(pedido_atual["estabelecimento_id"])
    if estabelecimento is None:
        return "Delivery indisponivel", 503
    conteudo = gerar_comprovante_pedido_pdf(pedido_atual, itens_pedido(pedido_atual["id"]), estabelecimento)
    return send_file(
        BytesIO(conteudo),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"pedido-{pedido_atual['id']}.pdf",
        max_age=0,
    )


@cliente_bp.get("/cliente/pedido/<int:pedido_id>")
def retorno_checkout_pedido(pedido_id):
    """Compatibilidade para preferencias antigas que usavam ID sequencial."""
    payment_id = request.args.get("payment_id", "").strip()
    if not payment_id:
        return "Pedido nao encontrado", 404
    try:
        from routes.pagamentos import MercadoPagoError, sincronizar_pagamento_pedido
        if sincronizar_pagamento_pedido(pedido_id, payment_id) is None:
            return "Retorno de pagamento invalido", 400
    except MercadoPagoError as erro:
        current_app.logger.warning(
            "Nao foi possivel confirmar o pagamento %s do pedido %s: %s", payment_id, pedido_id, erro.detalhes
        )
        return "Nao foi possivel confirmar o pagamento agora. Tente acompanhar o pedido novamente em instantes.", 502
    except Exception:
        current_app.logger.exception("Falha ao confirmar retorno do Checkout do pedido %s", pedido_id)
        return "Nao foi possivel confirmar o pagamento agora. Tente acompanhar o pedido novamente em instantes.", 502
    pedido_atual = obter_pedido(pedido_id)
    if pedido_atual is None:
        return "Pedido nao encontrado", 404
    return redirect(url_for("cliente.retorno_checkout_codigo", codigo=pedido_atual["codigo_acompanhamento"], retorno="checkout"))


@cliente_bp.get("/cliente/retorno/<codigo>")
def retorno_checkout_codigo(codigo):
    pedido_atual = obter_pedido_por_codigo(codigo)
    if pedido_atual is None:
        return "Pedido nao encontrado", 404
    payment_id = request.args.get("payment_id", "").strip()
    if payment_id:
        try:
            from routes.pagamentos import MercadoPagoError, sincronizar_pagamento_pedido
            sincronizar_pagamento_pedido(pedido_atual["id"], payment_id)
            pedido_atual = obter_pedido(pedido_atual["id"])
        except MercadoPagoError as erro:
            current_app.logger.warning(
                "Nao foi possivel confirmar o pagamento %s do pedido %s: %s", payment_id, pedido_atual["id"], erro.detalhes
            )
        except Exception:
            current_app.logger.exception("Falha ao confirmar retorno do Checkout do pedido %s", pedido_atual["id"])
    return renderizar_pedido(pedido_atual, retorno_checkout=bool(payment_id) or request.args.get("retorno") == "checkout")


@cliente_bp.get("/cliente/acompanhamento/<codigo>")
def pedido(codigo):
    pedido_atual = obter_pedido_por_codigo(codigo)
    if pedido_atual is None:
        return "Pedido nao encontrado", 404
    return renderizar_pedido(pedido_atual)


@cliente_bp.get("/cliente/acompanhamento/<codigo>/status")
def status_pedido(codigo):
    pedido_atual = obter_pedido_por_codigo(codigo)
    if pedido_atual is None:
        return jsonify(erro="Pedido nao encontrado"), 404
    return jsonify({
        "status_pagamento": pedido_atual["status_pagamento"],
        "status_operacional": pedido_atual["status_operacional"],
        "nome_status_operacional": STATUS_OPERACIONAL_NOMES.get(pedido_atual["status_operacional"], "Em atualizacao"),
    })


@cliente_bp.post("/cliente/acompanhamento/<codigo>/pagar")
def reiniciar_pagamento(codigo):
    pedido_atual = obter_pedido_por_codigo(codigo)
    if pedido_atual is None:
        return "Pedido nao encontrado", 404
    if pedido_atual["status_pagamento"] != "PENDENTE":
        flash("Este pedido nao esta aguardando um novo pagamento.", "warning")
        return redirect(url_for("cliente.pedido", codigo=pedido_atual["codigo_acompanhamento"]))
    session["pedido_pagamento_pendente"] = pedido_atual["id"]
    from routes.pagamentos import criar_checkout_pedido
    return criar_checkout_pedido(pedido_atual["id"])


@cliente_bp.route("/cliente/acompanhar", methods=["GET", "POST"])
def acompanhar_pedido():
    if request.method == "POST":
        codigo = request.form.get("codigo_acompanhamento", "").strip().replace(" ", "").upper()
        pedido_atual = obter_pedido_por_codigo(codigo)
        if pedido_atual is None:
            flash("Pedido nao encontrado. Confira o codigo informado.", "warning")
            return render_template("acompanhar.html"), 404
        return redirect(url_for("cliente.pedido", codigo=pedido_atual["codigo_acompanhamento"]))
    return render_template("acompanhar.html")
