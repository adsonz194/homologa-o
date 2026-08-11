from io import BytesIO
import math
from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, session, url_for

from models import (
    EstoqueInsuficiente,
    complementos_selecionados,
    confirmar_entrega_por_codigo,
    criar_pedido,
    detalhes_carrinho,
    itens_pedido,
    listar_locais_entrega,
    listar_complementos_por_produto,
    listar_produtos_disponiveis,
    obter_estabelecimento,
    obter_estabelecimento_por_slug,
    obter_url_publica_estabelecimento,
    obter_whatsapp_estabelecimento,
    obter_pedido,
    obter_pedido_por_codigo,
    obter_produto,
    quantidade_tentativas_entrega,
    registrar_tentativa_entrega,
    limpar_tentativas_entrega,
    obter_local_entrega,
    status_entrega_local,
    status_funcionamento_estabelecimento,
    data_hora_loja,
)
from nota_pdf import gerar_comprovante_pedido_pdf

cliente_bp = Blueprint("cliente", __name__)
FORMAS_PAGAMENTO = {"PIX", "CREDITO", "DEBITO", "DINHEIRO"}
MODALIDADES_ENTREGA = {"ENTREGA", "RETIRADA"}
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


def _valor_monetario(texto):
    valor = str(texto or "").strip().replace("R$", "").replace(" ", "")
    if "," in valor:
        valor = valor.replace(".", "").replace(",", ".")
    resultado = round(float(valor), 2)
    if not math.isfinite(resultado) or resultado < 0:
        raise ValueError
    return resultado


def carrinho_atual():
    bruto = session.get("carrinho", {})
    if not isinstance(bruto, dict):
        return {}

    # Carrinhos antigos usavam apenas o ID do produto como chave. Esta
    # normalizacao permite que eles continuem funcionando junto com itens
    # personalizados, sem misturar complementos de pedidos diferentes.
    carrinho = {}
    for chave_antiga, valor in bruto.items():
        try:
            if isinstance(valor, dict):
                produto_id = int(valor.get("produto_id"))
                quantidade = int(valor.get("quantidade"))
                complementos = sorted({int(item) for item in valor.get("complementos", [])})
            else:
                produto_id = int(chave_antiga)
                quantidade = int(valor)
                complementos = []
            if quantidade <= 0:
                continue
        except (TypeError, ValueError):
            continue
        chave = chave_item_carrinho(produto_id, complementos)
        if chave not in carrinho:
            carrinho[chave] = {"produto_id": produto_id, "quantidade": 0, "complementos": complementos}
        carrinho[chave]["quantidade"] += quantidade
    if carrinho != bruto:
        salvar_carrinho(carrinho)
    return carrinho


def salvar_carrinho(carrinho):
    session["carrinho"] = carrinho
    session.modified = True


def chave_item_carrinho(produto_id, complementos):
    sufixo = "-".join(str(item) for item in sorted(set(complementos))) or "sem"
    return f"{produto_id}--{sufixo}"


def quantidade_produto_no_carrinho(carrinho, produto_id, exceto_chave=None):
    return sum(
        int(item.get("quantidade", 0))
        for chave, item in carrinho.items()
        if chave != exceto_chave and int(item.get("produto_id", 0)) == produto_id
    )


def estabelecimento_principal():
    """A aplicacao voltou a operar somente o delivery principal."""
    return obter_estabelecimento_por_slug(current_app.config["ESTABELECIMENTO_PADRAO_SLUG"])


def renderizar_loja():
    estabelecimento = estabelecimento_principal()
    if estabelecimento is None:
        return "Delivery indisponivel", 503
    session["estabelecimento_publico_id"] = estabelecimento["id"]
    produtos = listar_produtos_disponiveis(estabelecimento["id"])
    produtos_por_categoria = {}
    for produto in produtos:
        produtos_por_categoria.setdefault(produto["categoria"] or "Geral", []).append(produto)
    carrinho = carrinho_atual()
    return render_template(
        "cliente.html",
        produtos=produtos,
        produtos_por_categoria=produtos_por_categoria,
        complementos_por_produto=listar_complementos_por_produto(produtos),
        quantidade_carrinho=sum(item["quantidade"] for item in carrinho.values()),
        estabelecimento=estabelecimento,
        funcionamento=status_funcionamento_estabelecimento(estabelecimento),
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
    try:
        ids_complementos = sorted({int(item) for item in request.form.getlist("complementos")})
    except ValueError:
        flash("Os complementos selecionados nao sao validos.", "warning")
        return redirect(url_for("cliente.loja"))
    complementos = complementos_selecionados(produto_id, ids_complementos)
    if len(complementos) != len(ids_complementos):
        flash("Um dos complementos nao esta mais disponivel. Escolha novamente.", "warning")
        return redirect(url_for("cliente.loja"))

    carrinho = carrinho_atual()
    chave = chave_item_carrinho(produto_id, ids_complementos)
    quantidade_no_carrinho = quantidade_produto_no_carrinho(carrinho, produto_id)
    if quantidade + quantidade_no_carrinho > produto["estoque"]:
        flash(f"Ha apenas {produto['estoque']} unidade(s) disponivel(is) deste produto.", "warning")
        return redirect(url_for("cliente.loja"))
    if chave not in carrinho:
        carrinho[chave] = {"produto_id": produto_id, "quantidade": 0, "complementos": ids_complementos}
    carrinho[chave]["quantidade"] += quantidade
    salvar_carrinho(carrinho)
    flash("Produto adicionado ao carrinho.", "success")
    return redirect(url_for("cliente.loja"))


@cliente_bp.get("/cliente/carrinho")
def carrinho():
    estabelecimento = estabelecimento_principal()
    if estabelecimento is None:
        return "Delivery indisponivel", 503
    funcionamento = status_funcionamento_estabelecimento(estabelecimento)
    itens = detalhes_carrinho(carrinho_atual(), estabelecimento["id"])
    subtotal = sum(item["subtotal"] for item in itens)
    total = subtotal + estabelecimento["valor_entrega"] if itens else subtotal
    return render_template(
        "carrinho.html", itens=itens, subtotal=subtotal, total=total, estabelecimento=estabelecimento,
        funcionamento=funcionamento,
    )


@cliente_bp.post("/cliente/carrinho/atualizar/<item_key>")
def atualizar_carrinho(item_key):
    estabelecimento = estabelecimento_principal()
    if estabelecimento is None:
        return "Delivery indisponivel", 503
    carrinho = carrinho_atual()
    try:
        quantidade = int(request.form["quantidade"])
    except (KeyError, ValueError):
        flash("Quantidade invalida.", "danger")
        return redirect(url_for("cliente.carrinho"))
    item = carrinho.get(item_key)
    if not isinstance(item, dict):
        flash("Item do carrinho nao encontrado.", "warning")
        return redirect(url_for("cliente.carrinho"))
    produto_id = item.get("produto_id")
    try:
        produto_id = int(produto_id)
    except (TypeError, ValueError):
        carrinho.pop(item_key, None)
        salvar_carrinho(carrinho)
        return redirect(url_for("cliente.carrinho"))
    produto = obter_produto(produto_id, estabelecimento["id"])
    if produto is None or not produto["disponivel"]:
        carrinho.pop(item_key, None)
        salvar_carrinho(carrinho)
        flash("Produto indisponivel removido do carrinho.", "warning")
        return redirect(url_for("cliente.carrinho"))
    if quantidade + quantidade_produto_no_carrinho(carrinho, produto_id, item_key) > produto["estoque"]:
        flash(f"Ha apenas {produto['estoque']} unidade(s) disponivel(is) deste produto.", "warning")
        return redirect(url_for("cliente.carrinho"))
    if quantidade <= 0:
        carrinho.pop(item_key, None)
    else:
        carrinho[item_key]["quantidade"] = quantidade
    salvar_carrinho(carrinho)
    return redirect(url_for("cliente.carrinho"))


@cliente_bp.route("/cliente/finalizar", methods=["GET", "POST"])
def finalizar():
    estabelecimento = estabelecimento_principal()
    if estabelecimento is None:
        return "Delivery indisponivel", 503
    funcionamento = status_funcionamento_estabelecimento(estabelecimento)
    itens = detalhes_carrinho(carrinho_atual(), estabelecimento["id"])
    if not itens:
        flash("Seu carrinho esta vazio.", "warning")
        return redirect(url_for("cliente.loja"))
    subtotal = sum(item["subtotal"] for item in itens)
    total = subtotal
    locais_entrega = listar_locais_entrega(estabelecimento["id"], somente_ativos=True)
    if request.method == "GET":
        return render_template("finalizar.html", itens=itens, subtotal=subtotal, total=total, estabelecimento=estabelecimento, locais_entrega=locais_entrega)
    cliente = request.form.get("cliente", "").strip()
    telefone = request.form.get("telefone", "").strip()
    endereco = request.form.get("endereco", "").strip()
    try:
        local_id = int(request.form.get("local_entrega", ""))
    except (TypeError, ValueError):
        local_id = None
    local = obter_local_entrega(local_id, estabelecimento["id"], somente_ativos=True) if local_id else None
    modalidade_entrega = request.form.get("modalidade_entrega", "ENTREGA")
    forma_pagamento = request.form.get("forma_pagamento", "")
    observacao = " ".join(request.form.get("observacao", "").split())
    agendado_texto = request.form.get("agendado_para", "").strip()
    agendado_para = None
    momento_atendimento = data_hora_loja()
    if agendado_texto:
        try:
            agendado = datetime.strptime(agendado_texto, "%Y-%m-%dT%H:%M")
            agora_local = data_hora_loja().replace(tzinfo=None)
            if not agora_local.replace(second=0, microsecond=0) < agendado <= agora_local.replace(second=0, microsecond=0) + timedelta(days=7):
                raise ValueError
            agendado_para = agendado.strftime("%Y-%m-%d %H:%M")
            momento_atendimento = agendado
        except ValueError:
            flash("Escolha um agendamento entre os proximos 7 dias.", "danger")
            return render_template("finalizar.html", itens=itens, subtotal=subtotal, total=total, estabelecimento=estabelecimento, locais_entrega=locais_entrega), 400
    elif not funcionamento["aberto"]:
        flash(f"{funcionamento['mensagem']} Escolha um horario para agendar o pedido.", "warning")
        return render_template("finalizar.html", itens=itens, subtotal=subtotal, total=total, estabelecimento=estabelecimento, locais_entrega=locais_entrega), 400
    if agendado_para:
        funcionamento_agendado = status_funcionamento_estabelecimento(estabelecimento, momento_atendimento)
        if not funcionamento_agendado["aberto"]:
            flash(f"A loja nao atende nesse horario. {funcionamento_agendado['mensagem']}", "warning")
            return render_template("finalizar.html", itens=itens, subtotal=subtotal, total=total, estabelecimento=estabelecimento, locais_entrega=locais_entrega), 400
    valor_recebido = None
    telefone_numeros = "".join(caractere for caractere in telefone if caractere.isdigit())
    if (
        not 2 <= len(cliente) <= 100
        or not 8 <= len(telefone_numeros) <= 15
        or len(observacao) > 500
        or modalidade_entrega not in MODALIDADES_ENTREGA
        or forma_pagamento not in FORMAS_PAGAMENTO
    ):
        flash("Confira nome, telefone, forma de pagamento e modalidade de recebimento.", "danger")
        return render_template("finalizar.html", itens=itens, subtotal=subtotal, total=total, estabelecimento=estabelecimento, locais_entrega=locais_entrega), 400
    if modalidade_entrega == "ENTREGA":
        if not 8 <= len(endereco) <= 300 or local is None:
            flash("Informe o local e o endereco completo para entrega.", "danger")
            return render_template("finalizar.html", itens=itens, subtotal=subtotal, total=total, estabelecimento=estabelecimento, locais_entrega=locais_entrega), 400
        funcionamento_local = status_entrega_local(estabelecimento, local, momento_atendimento)
        if not funcionamento_local["aberto"]:
            flash(funcionamento_local["mensagem"], "warning")
            return render_template("finalizar.html", itens=itens, subtotal=subtotal, total=total, estabelecimento=estabelecimento, locais_entrega=locais_entrega), 400
        local_entrega = local["nome"]
        valor_entrega = float(local["valor_entrega"])
        prazo_entrega_minutos = int(local["prazo_estimado_minutos"])
        if subtotal < float(local["pedido_minimo"]):
            flash(f"O pedido minimo para {local['nome']} e R$ {float(local['pedido_minimo']):.2f}.", "warning")
            return render_template("finalizar.html", itens=itens, subtotal=subtotal, total=total, estabelecimento=estabelecimento, locais_entrega=locais_entrega), 400
    else:
        endereco = "Retirada na loja"
        local_entrega = "Retirada na loja"
        valor_entrega = 0
        prazo_entrega_minutos = None
    total_cobravel = subtotal + valor_entrega
    if forma_pagamento == "DINHEIRO":
        try:
            valor_recebido = _valor_monetario(request.form.get("valor_recebido", ""))
        except (TypeError, ValueError):
            valor_recebido = -1
        if modalidade_entrega != "ENTREGA" or valor_recebido < total_cobravel:
            flash("Para pagamento em dinheiro, informe um valor igual ou maior que o total da entrega.", "danger")
            return render_template("finalizar.html", itens=itens, subtotal=subtotal, total=total, estabelecimento=estabelecimento, locais_entrega=locais_entrega), 400
    try:
        pedido_id = criar_pedido(
            cliente, telefone, endereco, local_entrega, modalidade_entrega, "", forma_pagamento,
            carrinho_atual(), estabelecimento["id"], valor_recebido,
            valor_entrega=valor_entrega, prazo_entrega_minutos=prazo_entrega_minutos,
            observacao=observacao, agendado_para=agendado_para,
        )
    except (EstoqueInsuficiente, ValueError) as erro:
        flash(str(erro), "danger")
        return redirect(url_for("cliente.carrinho"))
    session.pop("carrinho", None)
    pedido = obter_pedido(pedido_id)
    if forma_pagamento == "DINHEIRO":
        flash("Pedido registrado. O entregador levara o troco informado.", "success")
        return redirect(url_for("cliente.pedido", codigo=pedido["codigo_acompanhamento"]))
    session["pedido_pagamento_pendente"] = pedido_id
    # Mantemos o mesmo encadeamento HTTP simples que era usado no checkout
    # original: formulario -> rota do checkout -> Mercado Pago. Nao ha pagina
    # intermediaria nem JavaScript para o Safari/iPhone bloquear.
    return redirect(url_for("pagamentos.criar_checkout_pedido", pedido_id=pedido_id))


@cliente_bp.get("/cliente/pagamento/<int:pedido_id>/iniciar")
def iniciar_pagamento(pedido_id):
    if session.get("pedido_pagamento_pendente") != pedido_id:
        flash("Para sua seguranca, inicie o pagamento a partir do seu carrinho ou codigo de acompanhamento.", "warning")
        return redirect(url_for("cliente.loja"))
    pedido_atual = obter_pedido(pedido_id)
    if pedido_atual is None or pedido_atual["status_pagamento"] != "PENDENTE" or pedido_atual["forma_pagamento"] == "DINHEIRO":
        flash("Este pedido nao esta disponivel para um novo pagamento.", "warning")
        return redirect(url_for("cliente.loja"))
    return redirect(url_for("pagamentos.criar_checkout_pedido", pedido_id=pedido_id))


def renderizar_pedido(pedido_atual):
    codigo = pedido_atual["codigo_acompanhamento"]
    return render_template(
        "pedido.html",
        pedido=pedido_atual,
        codigo_acompanhamento=codigo,
        nome_status_operacional=STATUS_OPERACIONAL_NOMES.get(pedido_atual["status_operacional"], "Em atualizacao"),
        url_status=url_for("cliente.status_pedido", codigo=codigo),
        url_reiniciar_pagamento=url_for("cliente.reiniciar_pagamento", codigo=codigo),
        url_nota_pdf=url_for("cliente.nota_pdf", codigo=codigo),
        url_entrega=(
            f"{obter_url_publica_estabelecimento(pedido_atual['estabelecimento_id'])}"
            f"{url_for('cliente.confirmar_entrega', codigo=codigo)}"
        ) if pedido_atual["modalidade_entrega"] == "ENTREGA" else "",
        whatsapp_empresa=obter_whatsapp_estabelecimento(pedido_atual["estabelecimento_id"]),
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
    return renderizar_pedido(pedido_atual)


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


@cliente_bp.route("/entrega/<codigo>", methods=["GET", "POST"])
def confirmar_entrega(codigo):
    """Link publico do entregador: confirma somente com o codigo do cliente."""
    pedido_atual = obter_pedido_por_codigo(codigo)
    if pedido_atual is None or pedido_atual["modalidade_entrega"] != "ENTREGA":
        return "Entrega nao encontrada", 404
    if request.method == "POST":
        endereco_ip = request.remote_addr or "desconhecido"
        if quantidade_tentativas_entrega(pedido_atual["id"], endereco_ip, 900) >= 5:
            return "Muitas tentativas de codigo. Aguarde alguns minutos e tente novamente.", 429
        resultado = confirmar_entrega_por_codigo(pedido_atual["id"], request.form.get("codigo_entrega", ""))
        if resultado == "ENTREGUE":
            limpar_tentativas_entrega(pedido_atual["id"], endereco_ip)
            flash("Entrega confirmada com sucesso.", "success")
            return redirect(url_for("cliente.confirmar_entrega", codigo=pedido_atual["codigo_acompanhamento"]))
        if resultado == "CODIGO_INVALIDO":
            registrar_tentativa_entrega(pedido_atual["id"], endereco_ip)
            flash("Codigo de entrega invalido. Confira com o cliente.", "danger")
        elif resultado == "JA_ENTREGUE":
            flash("Esta entrega ja foi confirmada.", "info")
        else:
            flash("Esta entrega nao pode mais ser confirmada.", "warning")
        return redirect(url_for("cliente.confirmar_entrega", codigo=pedido_atual["codigo_acompanhamento"]))
    estabelecimento = obter_estabelecimento(pedido_atual["estabelecimento_id"])
    return render_template("entrega.html", pedido=pedido_atual, estabelecimento=estabelecimento)


@cliente_bp.post("/cliente/acompanhamento/<codigo>/pagar")
def reiniciar_pagamento(codigo):
    pedido_atual = obter_pedido_por_codigo(codigo)
    if pedido_atual is None:
        return "Pedido nao encontrado", 404
    if pedido_atual["status_pagamento"] != "PENDENTE" or pedido_atual["forma_pagamento"] == "DINHEIRO":
        flash("Este pedido nao esta aguardando um novo pagamento.", "warning")
        return redirect(url_for("cliente.pedido", codigo=pedido_atual["codigo_acompanhamento"]))
    session["pedido_pagamento_pendente"] = pedido_atual["id"]
    return redirect(url_for("pagamentos.criar_checkout_pedido", pedido_id=pedido_atual["id"]))


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
