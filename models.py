import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, time
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from werkzeug.security import check_password_hash

from database import gerar_codigo_acompanhamento, get_db
from licencas import validar_certificado


class EstoqueInsuficiente(ValueError):
    pass


FUSO_HORARIO_LOJA = ZoneInfo("America/Sao_Paulo")
DIAS_SEMANA = (
    (0, "Segunda-feira"), (1, "Terca-feira"), (2, "Quarta-feira"),
    (3, "Quinta-feira"), (4, "Sexta-feira"), (5, "Sabado"), (6, "Domingo"),
)
LOCAIS_ENTREGA = (
    ("IMBASSAI", "Imbassai", "00:00"),
    ("MARBELO", "Marbelo", "00:00"),
    ("MARASU", "Marasu", "20:00"),
)


def data_hora_loja():
    return datetime.now(FUSO_HORARIO_LOJA)


def status_funcionamento_estabelecimento(estabelecimento, agora=None):
    """Informa se o delivery pode receber novos pedidos neste momento."""
    agora = agora or data_hora_loja()
    hoje = agora.date()
    try:
        dias = {int(valor) for valor in str(estabelecimento["dias_funcionamento"] or "").split(",")}
    except (TypeError, ValueError):
        dias = set(range(7))
    try:
        abertura = time.fromisoformat(estabelecimento["horario_abertura"])
        encerramento = time.fromisoformat(estabelecimento["horario_encerramento"])
    except (TypeError, ValueError):
        abertura, encerramento = time(8), time(22)
    horario = f"{abertura.strftime('%H:%M')} às {encerramento.strftime('%H:%M')}"
    fechado_manual = str(estabelecimento["fechado_hoje_data"] or "") == hoje.isoformat()
    if fechado_manual:
        return {"aberto": False, "fechado_manual": True, "horario": horario, "mensagem": "O delivery está fechado hoje."}
    if hoje.weekday() not in dias:
        return {"aberto": False, "fechado_manual": False, "horario": horario, "mensagem": "O delivery não funciona hoje."}
    hora_atual = agora.timetz().replace(tzinfo=None)
    if hora_atual < abertura:
        return {"aberto": False, "fechado_manual": False, "horario": horario, "mensagem": f"O delivery abre hoje às {abertura.strftime('%H:%M')}."}
    # 00:00 representa a meia-noite do fim do dia, permitindo que a loja
    # trabalhe, por exemplo, das 08:00 até 00:00.
    if encerramento != time(0) and hora_atual >= encerramento:
        return {"aberto": False, "fechado_manual": False, "horario": horario, "mensagem": f"O delivery encerrou hoje às {encerramento.strftime('%H:%M')}."}
    return {"aberto": True, "fechado_manual": False, "horario": horario, "mensagem": f"Aberto agora. Atendimento até {encerramento.strftime('%H:%M')}."}


def local_entrega_por_codigo(codigo):
    return next((local for local in LOCAIS_ENTREGA if local[0] == codigo), None)


def status_entrega_local(estabelecimento, codigo_local, agora=None):
    """Combina a agenda geral com o limite específico de cada local."""
    status_loja = status_funcionamento_estabelecimento(estabelecimento, agora)
    if not status_loja["aberto"]:
        return status_loja
    local = local_entrega_por_codigo(codigo_local)
    if local is None:
        return {"aberto": False, "mensagem": "Este local não é atendido pelo delivery."}
    agora = agora or data_hora_loja()
    limite = time.fromisoformat(local[2])
    hora_atual = agora.timetz().replace(tzinfo=None)
    if limite != time(0) and hora_atual >= limite:
        return {
            "aberto": False,
            "mensagem": f"Não fazemos mais entregas em {local[1]} hoje. Atendimento até {local[2]}.",
        }
    return {"aberto": True, "mensagem": f"Entrega em {local[1]} disponível até {local[2]}."}


def obter_estabelecimento(estabelecimento_id):
    """Compatibilidade com a base existente: a interface usa somente a loja principal."""
    return get_db().execute(
        "SELECT * FROM estabelecimentos WHERE id = ?", (estabelecimento_id,)
    ).fetchone()


def obter_estabelecimento_por_slug(slug):
    return get_db().execute(
        "SELECT * FROM estabelecimentos WHERE slug = ? COLLATE NOCASE", (slug,)
    ).fetchone()


def _estabelecimento_integracao(estabelecimento_id=None):
    if estabelecimento_id is not None:
        return obter_estabelecimento(estabelecimento_id)
    return obter_estabelecimento_por_slug(current_app.config["ESTABELECIMENTO_PADRAO_SLUG"])


def _chave_fernet():
    """Retorna uma chave estavel para os segredos salvos pelo painel.

    CONFIG_ENCRYPTION_KEY permite trocar a SECRET_KEY sem invalidar os
    segredos. Na ausencia dela, a SECRET_KEY ja obrigatoria em producao e
    usada para derivar uma chave Fernet valida.
    """
    chave = current_app.config["CONFIG_ENCRYPTION_KEY"].strip()
    if chave:
        return chave.encode("utf-8")
    material = current_app.config["SECRET_KEY"].encode("utf-8")
    return base64.urlsafe_b64encode(hashlib.sha256(material).digest())


def _criptografar_configuracao(valor):
    if not valor:
        return None
    return "v1:" + Fernet(_chave_fernet()).encrypt(valor.encode("utf-8")).decode("utf-8")


def _descriptografar_configuracao(valor):
    if not valor or not str(valor).startswith("v1:"):
        return ""
    try:
        return Fernet(_chave_fernet()).decrypt(str(valor)[3:].encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        current_app.logger.warning("Uma credencial salva no painel nao pode ser lida com a chave atual.")
        return ""


def status_certificado_estabelecimento(estabelecimento):
    """Retorna o estado da licenca, sempre conferindo a assinatura do certificado."""
    chave = current_app.config["LICENSE_SIGNING_KEY"]
    certificado = _descriptografar_configuracao(estabelecimento["certificado_licenca_criptografado"])
    if not chave and not current_app.config["LICENSE_ENFORCEMENT"]:
        return {
            "valido": True,
            "status": "NAO_OBRIGATORIO",
            "mensagem": "A validacao obrigatoria de certificado esta desativada.",
            "obrigatorio": False,
        }
    if not chave:
        return {
            "valido": False,
            "status": "CONFIGURACAO_INCOMPLETA",
            "mensagem": "A chave de validacao do certificado ainda nao foi configurada.",
            "obrigatorio": True,
        }
    if not certificado:
        if not current_app.config["LICENSE_ENFORCEMENT"]:
            return {
                "valido": True,
                "status": "SEM_CERTIFICADO",
                "mensagem": "Nenhum certificado foi validado; a obrigatoriedade esta desativada.",
                "obrigatorio": False,
            }
        return {
            "valido": False,
            "status": "SEM_CERTIFICADO",
            "mensagem": "Nenhum certificado de licenca foi validado nesta instalacao.",
            "obrigatorio": True,
        }
    resultado = validar_certificado(
        certificado,
        estabelecimento["identificador_instalacao"],
        chave,
    )
    resultado["obrigatorio"] = current_app.config["LICENSE_ENFORCEMENT"]
    if not current_app.config["LICENSE_ENFORCEMENT"] and not resultado["valido"]:
        resultado["mensagem"] += " A obrigatoriedade esta desativada."
    return resultado


def validar_e_salvar_certificado(estabelecimento_id, certificado):
    """Aceita somente um certificado assinado e valido para esta instalacao."""
    estabelecimento = obter_estabelecimento(estabelecimento_id)
    if estabelecimento is None:
        return {"valido": False, "status": "NAO_ENCONTRADO", "mensagem": "Estabelecimento nao encontrado."}
    chave = current_app.config["LICENSE_SIGNING_KEY"]
    if not chave:
        return {
            "valido": False,
            "status": "CONFIGURACAO_INCOMPLETA",
            "mensagem": "A chave de validacao ainda nao foi configurada pelo fornecedor.",
        }
    resultado = validar_certificado(certificado, estabelecimento["identificador_instalacao"], chave)
    if not resultado["valido"]:
        return resultado
    db = get_db()
    db.execute(
        """UPDATE estabelecimentos
           SET certificado_licenca_criptografado = ?, certificado_ativado_em = CURRENT_TIMESTAMP,
               certificado_expira_em = ?
           WHERE id = ?""",
        (_criptografar_configuracao(str(certificado).strip()), resultado["expira_em"].isoformat(), estabelecimento_id),
    )
    db.commit()
    return resultado


def obter_token_mercadopago(estabelecimento_id=None):
    estabelecimento = _estabelecimento_integracao(estabelecimento_id)
    if estabelecimento is not None:
        token = _descriptografar_configuracao(estabelecimento["mercadopago_token_criptografado"])
        if token:
            return token
    return current_app.config["MERCADOPAGO_ACCESS_TOKEN"]


def obter_segredo_webhook_mercadopago(estabelecimento_id=None):
    estabelecimento = _estabelecimento_integracao(estabelecimento_id)
    if estabelecimento is not None:
        segredo = _descriptografar_configuracao(estabelecimento["webhook_secret_criptografado"])
        if segredo:
            return segredo
    return current_app.config["MERCADOPAGO_WEBHOOK_SECRET"]


def obter_whatsapp_estabelecimento(estabelecimento_id=None):
    estabelecimento = _estabelecimento_integracao(estabelecimento_id)
    telefone = estabelecimento["whatsapp"] if estabelecimento is not None else ""
    somente_numeros = "".join(caractere for caractere in telefone if caractere.isdigit())
    return somente_numeros or current_app.config["WHATSAPP_EMPRESA"]


def obter_url_publica_estabelecimento(estabelecimento_id=None):
    estabelecimento = _estabelecimento_integracao(estabelecimento_id)
    url = (estabelecimento["url_publica"] if estabelecimento is not None else "").strip().rstrip("/")
    endereco = urlparse(url)
    if endereco.scheme == "https" and endereco.hostname:
        return url
    return current_app.config["BASE_URL"].rstrip("/")


def atualizar_configuracao_estabelecimento(
    estabelecimento_id, nome, razao_social, cnpj, endereco, telefone, whatsapp, valor_entrega, url_publica, dias_funcionamento,
    horario_abertura, horario_encerramento, access_token="", webhook_secret=""
):
    """Atualiza configuracoes da loja sem devolver credenciais ao navegador."""
    campos = [
        "nome = ?", "razao_social = ?", "cnpj = ?", "endereco = ?", "telefone = ?", "whatsapp = ?", "valor_entrega = ?", "url_publica = ?",
        "dias_funcionamento = ?", "horario_abertura = ?", "horario_encerramento = ?",
    ]
    valores = [nome, razao_social, cnpj, endereco, telefone, whatsapp, valor_entrega, url_publica, dias_funcionamento, horario_abertura, horario_encerramento]
    if access_token:
        campos.append("mercadopago_token_criptografado = ?")
        valores.append(_criptografar_configuracao(access_token))
    if webhook_secret:
        campos.append("webhook_secret_criptografado = ?")
        valores.append(_criptografar_configuracao(webhook_secret))
    valores.append(estabelecimento_id)
    db = get_db()
    db.execute(
        f"UPDATE estabelecimentos SET {', '.join(campos)} WHERE id = ?",
        valores,
    )
    db.commit()


def definir_fechado_hoje(estabelecimento_id, fechado):
    db = get_db()
    db.execute(
        "UPDATE estabelecimentos SET fechado_hoje_data = ? WHERE id = ?",
        (data_hora_loja().date().isoformat() if fechado else None, estabelecimento_id),
    )
    db.commit()


def criar_venda(cliente, produto, quantidade, valor_unitario, desconto, forma_pagamento, produto_id=None, canal_venda="INTERNA", estabelecimento_id=None):
    total = max(0, quantidade * valor_unitario - desconto)
    db = get_db()
    with db:
        estoque_reservado = 0
        if produto_id is not None:
            cadastro = db.execute("SELECT disponivel, estoque FROM produtos WHERE id = ? AND estabelecimento_id = ?", (produto_id, estabelecimento_id)).fetchone()
            if cadastro is None or not cadastro["disponivel"] or cadastro["estoque"] < quantidade:
                raise EstoqueInsuficiente("Produto indisponivel ou sem estoque suficiente.")
            db.execute("UPDATE produtos SET estoque = estoque - ? WHERE id = ? AND estabelecimento_id = ?", (quantidade, produto_id, estabelecimento_id))
            estoque_reservado = 1
        cursor = db.execute(
            """INSERT INTO vendas
               (cliente, produto, quantidade, valor_unitario, desconto, valor_total, forma_pagamento, produto_id, canal_venda, estoque_reservado, estabelecimento_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cliente, produto, quantidade, valor_unitario, desconto, total, forma_pagamento, produto_id, canal_venda, estoque_reservado, estabelecimento_id),
        )
    return cursor.lastrowid


def obter_venda(venda_id, estabelecimento_id=None):
    consulta = "SELECT * FROM vendas WHERE id = ?"
    parametros = [venda_id]
    if estabelecimento_id is not None:
        consulta += " AND estabelecimento_id = ?"
        parametros.append(estabelecimento_id)
    return get_db().execute(consulta, parametros).fetchone()


def listar_vendas(estabelecimento_id):
    return get_db().execute("SELECT * FROM vendas WHERE estabelecimento_id = ? ORDER BY id DESC", (estabelecimento_id,)).fetchall()


def relatorio_vendas(estabelecimento_id, data_inicio, data_fim):
    """Itens de venda interna e delivery para o relatorio imprimivel."""
    linhas = get_db().execute(
        """SELECT 'INTERNA' AS canal, id, cliente,
                  produto || ' × ' || quantidade AS descricao, forma_pagamento,
                  valor_total, status_pagamento, criado_em
           FROM vendas
           WHERE estabelecimento_id = ? AND date(criado_em) BETWEEN date(?) AND date(?)
           UNION ALL
           SELECT 'DELIVERY' AS canal, pedidos.id, pedidos.cliente,
                  COALESCE(GROUP_CONCAT(pedido_itens.quantidade || ' × ' || pedido_itens.descricao, ', '), ''),
                  pedidos.forma_pagamento, pedidos.valor_total, pedidos.status_pagamento, pedidos.criado_em
           FROM pedidos LEFT JOIN pedido_itens ON pedido_itens.pedido_id = pedidos.id
           WHERE pedidos.estabelecimento_id = ? AND date(pedidos.criado_em) BETWEEN date(?) AND date(?)
           GROUP BY pedidos.id
           ORDER BY criado_em DESC, canal""",
        (estabelecimento_id, data_inicio, data_fim, estabelecimento_id, data_inicio, data_fim),
    ).fetchall()
    resumo = {
        "quantidade": len(linhas),
        "aprovadas": sum(1 for linha in linhas if linha["status_pagamento"] == "APROVADO"),
        "pendentes": sum(1 for linha in linhas if linha["status_pagamento"] == "PENDENTE"),
        "recebido": sum(linha["valor_total"] for linha in linhas if linha["status_pagamento"] == "APROVADO"),
    }
    return linhas, resumo


def atualizar_preferencia(venda_id, preference_id):
    db = get_db()
    db.execute("UPDATE vendas SET preference_id = ? WHERE id = ?", (preference_id, venda_id))
    db.commit()


def atualizar_pagamento(venda_id, status, payment_id=None):
    db = get_db()
    with db:
        venda = obter_venda(venda_id)
        if venda is None:
            return
        if status in {"REJEITADO", "CANCELADO"} and venda["estoque_reservado"] and venda["produto_id"]:
            db.execute("UPDATE produtos SET estoque = estoque + ? WHERE id = ?", (venda["quantidade"], venda["produto_id"]))
            db.execute("UPDATE vendas SET estoque_reservado = 0 WHERE id = ?", (venda_id,))
        db.execute(
            "UPDATE vendas SET status_pagamento = ?, payment_id = COALESCE(?, payment_id) WHERE id = ?",
            (status, payment_id, venda_id),
        )


def criar_produto(codigo_interno, ean, descricao, valor_unitario, estoque, disponivel, estabelecimento_id):
    db = get_db()
    cursor = db.execute(
        """INSERT INTO produtos (codigo_interno, ean, descricao, valor_unitario, estoque, disponivel, estabelecimento_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (codigo_interno, ean or None, descricao, valor_unitario, estoque, int(disponivel), estabelecimento_id),
    )
    db.commit()
    return cursor.lastrowid


def atualizar_produto(produto_id, codigo_interno, ean, descricao, valor_unitario, estoque, disponivel, estabelecimento_id):
    db = get_db()
    db.execute(
        """UPDATE produtos SET codigo_interno = ?, ean = ?, descricao = ?, valor_unitario = ?, estoque = ?, disponivel = ?
           WHERE id = ? AND estabelecimento_id = ?""",
        (codigo_interno, ean or None, descricao, valor_unitario, estoque, int(disponivel), produto_id, estabelecimento_id),
    )
    db.commit()


def listar_complementos_produto(produto_id, somente_ativos=True):
    consulta = "SELECT * FROM produto_complementos WHERE produto_id = ?"
    parametros = [produto_id]
    if somente_ativos:
        consulta += " AND ativo = 1"
    consulta += " ORDER BY descricao COLLATE NOCASE, id"
    return get_db().execute(consulta, parametros).fetchall()


def listar_complementos_por_produto(produtos):
    """Agrupa os complementos ativos sem expor opcoes de outro produto."""
    ids = [produto["id"] for produto in produtos]
    resultado = {produto_id: [] for produto_id in ids}
    if not ids:
        return resultado
    marcadores = ", ".join("?" for _ in ids)
    linhas = get_db().execute(
        f"""SELECT * FROM produto_complementos
            WHERE ativo = 1 AND produto_id IN ({marcadores})
            ORDER BY descricao COLLATE NOCASE, id""",
        ids,
    ).fetchall()
    for complemento in linhas:
        resultado.setdefault(complemento["produto_id"], []).append(complemento)
    return resultado


def substituir_complementos_produto(produto_id, complementos):
    """Salva a lista atual de complementos; pedidos antigos mantem sua descricao."""
    db = get_db()
    with db:
        db.execute("DELETE FROM produto_complementos WHERE produto_id = ?", (produto_id,))
        db.executemany(
            """INSERT INTO produto_complementos (produto_id, descricao, valor_adicional)
               VALUES (?, ?, ?)""",
            [(produto_id, item["descricao"], item["valor_adicional"]) for item in complementos],
        )


def complementos_selecionados(produto_id, ids_complementos):
    """Retorna somente complementos ativos que realmente pertencem ao produto."""
    ids = sorted({int(complemento_id) for complemento_id in ids_complementos})
    if not ids:
        return []
    marcadores = ", ".join("?" for _ in ids)
    return get_db().execute(
        f"""SELECT * FROM produto_complementos
            WHERE produto_id = ? AND ativo = 1 AND id IN ({marcadores})
            ORDER BY descricao COLLATE NOCASE, id""",
        [produto_id, *ids],
    ).fetchall()


def listar_produtos(estabelecimento_id):
    return get_db().execute("SELECT * FROM produtos WHERE estabelecimento_id = ? ORDER BY descricao COLLATE NOCASE", (estabelecimento_id,)).fetchall()


def listar_produtos_disponiveis(estabelecimento_id):
    return get_db().execute(
        "SELECT * FROM produtos WHERE estabelecimento_id = ? AND disponivel = 1 AND estoque > 0 ORDER BY descricao COLLATE NOCASE", (estabelecimento_id,)
    ).fetchall()


def obter_produto(produto_id, estabelecimento_id=None):
    consulta = "SELECT * FROM produtos WHERE id = ?"
    parametros = [produto_id]
    if estabelecimento_id is not None:
        consulta += " AND estabelecimento_id = ?"
        parametros.append(estabelecimento_id)
    return get_db().execute(consulta, parametros).fetchone()


def buscar_produtos(consulta, estabelecimento_id, limite=10):
    termo_inicio = f"{consulta}%"
    termo_descricao = f"%{consulta}%"
    return get_db().execute(
        """SELECT * FROM produtos
           WHERE estabelecimento_id = ? AND disponivel = 1 AND estoque > 0
             AND (ean LIKE ? OR codigo_interno LIKE ? OR descricao LIKE ? COLLATE NOCASE)
           ORDER BY CASE
               WHEN ean = ? THEN 0
               WHEN codigo_interno = ? THEN 1
               WHEN descricao = ? COLLATE NOCASE THEN 2
               ELSE 3 END, descricao COLLATE NOCASE
           LIMIT ?""",
        (estabelecimento_id, termo_inicio, termo_inicio, termo_descricao, consulta, consulta, consulta, limite),
    ).fetchall()


def detalhes_carrinho(carrinho, estabelecimento_id):
    itens = []
    for chave, entrada in carrinho.items():
        try:
            # Compatibilidade com os carrinhos salvos antes dos complementos,
            # que eram somente {"id_do_produto": quantidade}.
            if isinstance(entrada, dict):
                produto_id = int(entrada.get("produto_id"))
                quantidade = int(entrada.get("quantidade"))
                ids_complementos = entrada.get("complementos", [])
            else:
                produto_id = int(chave)
                quantidade = int(entrada)
                ids_complementos = []
            produto = obter_produto(produto_id, estabelecimento_id)
            complementos = complementos_selecionados(produto_id, ids_complementos)
        except (TypeError, ValueError):
            continue
        if produto is not None and quantidade > 0:
            valor_complementos = sum(complemento["valor_adicional"] for complemento in complementos)
            valor_unitario = produto["valor_unitario"] + valor_complementos
            nomes_complementos = ", ".join(complemento["descricao"] for complemento in complementos)
            descricao = produto["descricao"]
            if nomes_complementos:
                descricao += f" (Complementos: {nomes_complementos})"
            itens.append({
                "chave": str(chave),
                "produto": produto,
                "complementos": complementos,
                "quantidade": quantidade,
                "valor_complementos": valor_complementos,
                "valor_unitario": valor_unitario,
                "descricao": descricao,
                "subtotal": valor_unitario * quantidade,
            })
    return itens


def gerar_codigo_entrega():
    """Codigo curto informado pelo cliente ao entregador no destino."""
    return f"{secrets.randbelow(900_000) + 100_000}"


def criar_pedido(
    cliente, telefone, endereco, local_entrega, modalidade_entrega, email,
    forma_pagamento, carrinho, estabelecimento_id, valor_recebido=None,
):
    itens = detalhes_carrinho(carrinho, estabelecimento_id)
    if not itens:
        raise EstoqueInsuficiente("Carrinho vazio.")
    estabelecimento = obter_estabelecimento(estabelecimento_id)
    if estabelecimento is None:
        raise EstoqueInsuficiente("Estabelecimento indisponivel.")
    db = get_db()
    with db:
        valor_entrega = estabelecimento["valor_entrega"] if modalidade_entrega == "ENTREGA" else 0
        total = valor_entrega
        for item in itens:
            produto = db.execute("SELECT * FROM produtos WHERE id = ? AND estabelecimento_id = ?", (item["produto"]["id"], estabelecimento_id)).fetchone()
            if produto is None or not produto["disponivel"] or produto["estoque"] < item["quantidade"]:
                raise EstoqueInsuficiente(f"{item['produto']['descricao']} nao possui estoque suficiente.")
            item["produto"] = produto
            total += item["subtotal"]
        if forma_pagamento == "DINHEIRO":
            if modalidade_entrega != "ENTREGA" or valor_recebido is None or valor_recebido < total:
                raise ValueError("Informe um valor em dinheiro igual ou maior que o total do pedido.")
            troco = round(valor_recebido - total, 2)
            status_operacional = "FILA_DE_ESPERA"
        else:
            valor_recebido = None
            troco = 0
            status_operacional = "PENDENTE"
        codigo_acompanhamento = gerar_codigo_acompanhamento(db)
        codigo_entrega = gerar_codigo_entrega() if modalidade_entrega == "ENTREGA" else None
        cursor = db.execute(
            """INSERT INTO pedidos
               (cliente, telefone, endereco, local_entrega, modalidade_entrega, email, forma_pagamento, valor_total, valor_entrega,
                valor_recebido, troco, codigo_acompanhamento, codigo_entrega, status_operacional, estabelecimento_id, estoque_reservado)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                cliente, telefone, endereco, local_entrega, modalidade_entrega, email, forma_pagamento, total, valor_entrega,
                valor_recebido, troco, codigo_acompanhamento, codigo_entrega, status_operacional, estabelecimento_id,
            ),
        )
        pedido_id = cursor.lastrowid
        for item in itens:
            produto = item["produto"]
            db.execute(
                """INSERT INTO pedido_itens (pedido_id, produto_id, descricao, quantidade, valor_unitario)
                   VALUES (?, ?, ?, ?, ?)""",
                (pedido_id, produto["id"], item["descricao"], item["quantidade"], item["valor_unitario"]),
            )
    return pedido_id


def obter_pedido(pedido_id):
    return get_db().execute("SELECT * FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()


def obter_pedido_por_codigo(codigo):
    return get_db().execute(
        "SELECT * FROM pedidos WHERE codigo_acompanhamento = ?", (codigo.upper(),)
    ).fetchone()


def itens_pedido(pedido_id):
    return get_db().execute(
        """SELECT pedido_itens.*, produtos.codigo_interno
           FROM pedido_itens LEFT JOIN produtos ON produtos.id = pedido_itens.produto_id
           WHERE pedido_itens.pedido_id = ?""",
        (pedido_id,),
    ).fetchall()


def listar_pedidos(estabelecimento_id):
    return get_db().execute(
        """SELECT pedidos.*, GROUP_CONCAT(pedido_itens.quantidade || 'x ' || pedido_itens.descricao, ', ') AS itens
           FROM pedidos LEFT JOIN pedido_itens ON pedido_itens.pedido_id = pedidos.id
           WHERE pedidos.estabelecimento_id = ? GROUP BY pedidos.id ORDER BY pedidos.id DESC""", (estabelecimento_id,)
    ).fetchall()


def listar_pedidos_aprovados_apos(estabelecimento_id, depois_id):
    """Pedidos recebidos pelo painel, inclusive dinheiro na entrega."""
    return get_db().execute(
        """SELECT id, cliente, valor_total, local_entrega
           FROM pedidos
           WHERE estabelecimento_id = ? AND id > ?
             AND (status_pagamento = 'APROVADO'
                  OR (forma_pagamento = 'DINHEIRO' AND status_operacional = 'FILA_DE_ESPERA'))
           ORDER BY id ASC LIMIT 30""",
        (estabelecimento_id, depois_id),
    ).fetchall()


def atualizar_preferencia_pedido(pedido_id, preference_id):
    db = get_db()
    db.execute("UPDATE pedidos SET preference_id = ? WHERE id = ?", (preference_id, pedido_id))
    db.commit()


def registrar_pix_pedido(pedido_id, mercadopago_order_id, payment_id, qr_code, qr_code_base64):
    db = get_db()
    db.execute(
        """UPDATE pedidos SET mercadopago_order_id = ?, payment_id = ?, pix_qr_code = ?, pix_qr_code_base64 = ?
           WHERE id = ?""",
        (mercadopago_order_id, payment_id, qr_code, qr_code_base64, pedido_id),
    )
    db.commit()


def _atualizar_pagamento_pedido_no_banco(db, pedido, status, payment_id=None):
    """Atualiza pagamento e estoque usando a mesma transacao SQLite."""
    pedido_id = pedido["id"]
    if status == "APROVADO" and not pedido["estoque_reservado"]:
        # O carrinho e o pedido pendente nao reservam estoque. Esta atualizacao
        # condicional impede que retorno do checkout e webhook baixem duas vezes.
        baixa_confirmada = db.execute(
            "UPDATE pedidos SET estoque_reservado = 1 WHERE id = ? AND estoque_reservado = 0",
            (pedido_id,),
        ).rowcount
        if baixa_confirmada:
            itens = db.execute("SELECT * FROM pedido_itens WHERE pedido_id = ?", (pedido_id,)).fetchall()
            for item in itens:
                db.execute(
                    """UPDATE produtos SET estoque = estoque - ?
                       WHERE id = ? AND estabelecimento_id = ?""",
                    (item["quantidade"], item["produto_id"], pedido["estabelecimento_id"]),
                )
    if status in {"REJEITADO", "CANCELADO"} and pedido["estoque_reservado"]:
        itens = db.execute("SELECT * FROM pedido_itens WHERE pedido_id = ?", (pedido_id,)).fetchall()
        for item in itens:
            db.execute("UPDATE produtos SET estoque = estoque + ? WHERE id = ?", (item["quantidade"], item["produto_id"]))
        db.execute("UPDATE pedidos SET estoque_reservado = 0 WHERE id = ?", (pedido_id,))
    if status == "APROVADO" and pedido["status_operacional"] == "PENDENTE":
        db.execute(
            "UPDATE pedidos SET status_operacional = 'FILA_DE_ESPERA' WHERE id = ?",
            (pedido_id,),
        )
    db.execute(
        "UPDATE pedidos SET status_pagamento = ?, payment_id = COALESCE(?, payment_id) WHERE id = ?",
        (status, payment_id, pedido_id),
    )


def atualizar_pagamento_pedido(pedido_id, status, payment_id=None):
    db = get_db()
    with db:
        pedido = db.execute("SELECT * FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()
        if pedido is None:
            return
        _atualizar_pagamento_pedido_no_banco(db, pedido, status, payment_id)


def confirmar_entrega_por_codigo(pedido_id, codigo_entrega):
    """Confirma entrega no link publico depois de validar o codigo do cliente."""
    codigo = "".join(caractere for caractere in str(codigo_entrega or "") if caractere.isdigit())
    db = get_db()
    with db:
        pedido = db.execute("SELECT * FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()
        if pedido is None or pedido["modalidade_entrega"] != "ENTREGA":
            return "NAO_ENCONTRADO"
        if pedido["status_operacional"] == "ENTREGUE":
            return "JA_ENTREGUE"
        if pedido["status_operacional"] in {"CANCELADO", "EXTRAVIADO"}:
            return "INDISPONIVEL"
        if not pedido["codigo_entrega"] or not hmac.compare_digest(str(pedido["codigo_entrega"]), codigo):
            return "CODIGO_INVALIDO"
        if pedido["forma_pagamento"] == "DINHEIRO" and pedido["status_pagamento"] == "PENDENTE":
            _atualizar_pagamento_pedido_no_banco(db, pedido, "APROVADO")
        db.execute(
            "UPDATE pedidos SET status_operacional = 'ENTREGUE', entregue_em = CURRENT_TIMESTAMP WHERE id = ?",
            (pedido_id,),
        )
    return "ENTREGUE"


def liberar_estoque_pedido(pedido_id):
    db = get_db()
    with db:
        pedido = obter_pedido(pedido_id)
        if pedido is None or not pedido["estoque_reservado"]:
            return
        for item in itens_pedido(pedido_id):
            db.execute("UPDATE produtos SET estoque = estoque + ? WHERE id = ?", (item["quantidade"], item["produto_id"]))
        db.execute("UPDATE pedidos SET estoque_reservado = 0 WHERE id = ?", (pedido_id,))


def atualizar_status_operacional_pedido(pedido_id, status):
    db = get_db()
    db.execute("UPDATE pedidos SET status_operacional = ? WHERE id = ?", (status, pedido_id))
    db.commit()


def obter_usuario_por_nome(usuario):
    return get_db().execute(
        "SELECT * FROM usuarios WHERE usuario = ? COLLATE NOCASE AND ativo = 1", (usuario,)
    ).fetchone()


def email_recuperacao_valido(email):
    """Valida o endereco usado apenas para recuperar a conta do dono."""
    return bool(re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,63}", str(email or "")))


def atualizar_email_recuperacao(usuario_id, email):
    """Troca o e-mail e invalida codigos antigos para evitar uso indevido."""
    db = get_db()
    with db:
        db.execute(
            "UPDATE usuarios SET email_recuperacao = ? WHERE id = ? AND papel = 'DONO'",
            (email.strip().lower(), usuario_id),
        )
        db.execute(
            "UPDATE recuperacoes_senha SET usado_em = CURRENT_TIMESTAMP WHERE usuario_id = ? AND usado_em IS NULL",
            (usuario_id,),
        )


def email_recuperacao_em_uso(usuario_id, email):
    if not email:
        return False
    return get_db().execute(
        """SELECT 1 FROM usuarios
           WHERE email_recuperacao = ? COLLATE NOCASE AND id <> ? LIMIT 1""",
        (email, usuario_id),
    ).fetchone() is not None


def obter_usuario_por_recuperacao(identificador):
    """Localiza uma conta ativa por usuario ou pelo e-mail de recuperacao."""
    valor = str(identificador or "").strip()
    return get_db().execute(
        """SELECT * FROM usuarios
           WHERE ativo = 1 AND (usuario = ? COLLATE NOCASE OR email_recuperacao = ? COLLATE NOCASE)
           LIMIT 1""",
        (valor, valor),
    ).fetchone()


def criar_recuperacao_senha(usuario_id, codigo_hash, minutos_validade):
    """Mantem somente um codigo de recuperacao ativo por usuario."""
    db = get_db()
    minutos = max(1, int(minutos_validade))
    with db:
        db.execute(
            "UPDATE recuperacoes_senha SET usado_em = CURRENT_TIMESTAMP WHERE usuario_id = ? AND usado_em IS NULL",
            (usuario_id,),
        )
        db.execute(
            """INSERT INTO recuperacoes_senha (usuario_id, codigo_hash, expira_em)
               VALUES (?, ?, datetime('now', ?))""",
            (usuario_id, codigo_hash, f"+{minutos} minutes"),
        )


def invalidar_recuperacoes_senha(usuario_id):
    db = get_db()
    with db:
        db.execute(
            "UPDATE recuperacoes_senha SET usado_em = CURRENT_TIMESTAMP WHERE usuario_id = ? AND usado_em IS NULL",
            (usuario_id,),
        )


def redefinir_senha_com_codigo(identificador, codigo, nova_senha_hash, max_tentativas):
    """Valida um codigo de uso unico e troca a senha sem revelar dados da conta."""
    usuario = obter_usuario_por_recuperacao(identificador)
    if usuario is None:
        return "CODIGO_INVALIDO"
    db = get_db()
    limite = max(1, int(max_tentativas))
    with db:
        recuperacao = db.execute(
            """SELECT * FROM recuperacoes_senha
               WHERE usuario_id = ? AND usado_em IS NULL
               ORDER BY id DESC LIMIT 1""",
            (usuario["id"],),
        ).fetchone()
        agora = db.execute("SELECT datetime('now') AS agora").fetchone()["agora"]
        if recuperacao is None or recuperacao["expira_em"] <= agora:
            if recuperacao is not None:
                db.execute("UPDATE recuperacoes_senha SET usado_em = CURRENT_TIMESTAMP WHERE id = ?", (recuperacao["id"],))
            return "CODIGO_EXPIRADO"
        if recuperacao["tentativas"] >= limite:
            db.execute("UPDATE recuperacoes_senha SET usado_em = CURRENT_TIMESTAMP WHERE id = ?", (recuperacao["id"],))
            return "CODIGO_BLOQUEADO"
        if not check_password_hash(recuperacao["codigo_hash"], str(codigo or "")):
            tentativas = recuperacao["tentativas"] + 1
            usado_em = "CURRENT_TIMESTAMP" if tentativas >= limite else "NULL"
            db.execute(
                f"UPDATE recuperacoes_senha SET tentativas = ?, usado_em = {usado_em} WHERE id = ?",
                (tentativas, recuperacao["id"]),
            )
            return "CODIGO_BLOQUEADO" if tentativas >= limite else "CODIGO_INVALIDO"
        db.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (nova_senha_hash, usuario["id"]))
        db.execute("UPDATE recuperacoes_senha SET usado_em = CURRENT_TIMESTAMP WHERE id = ?", (recuperacao["id"],))
    return "SUCESSO"


def quantidade_solicitacoes_recuperacao(endereco_ip, janela_segundos):
    db = get_db()
    segundos = max(1, int(janela_segundos))
    with db:
        db.execute("DELETE FROM solicitacoes_recuperacao_senha WHERE criado_em < datetime('now', '-1 day')")
        return db.execute(
            """SELECT COUNT(*) AS total FROM solicitacoes_recuperacao_senha
               WHERE endereco_ip = ? AND criado_em >= datetime('now', ?)""",
            (endereco_ip, f"-{segundos} seconds"),
        ).fetchone()["total"]


def registrar_solicitacao_recuperacao(endereco_ip):
    db = get_db()
    with db:
        db.execute(
            "INSERT INTO solicitacoes_recuperacao_senha (endereco_ip) VALUES (?)",
            (endereco_ip,),
        )


def quantidade_tentativas_login(endereco_ip, janela_segundos):
    """Retorna falhas recentes de login e remove registros antigos."""
    db = get_db()
    db.execute(
        "DELETE FROM tentativas_login WHERE criado_em < datetime('now', '-1 day')"
    )
    total = db.execute(
        """SELECT COUNT(*) AS total FROM tentativas_login
           WHERE endereco_ip = ? AND criado_em >= datetime('now', ?)""",
        (endereco_ip, f"-{janela_segundos} seconds"),
    ).fetchone()["total"]
    db.commit()
    return total


def registrar_tentativa_login(endereco_ip):
    db = get_db()
    db.execute("INSERT INTO tentativas_login (endereco_ip) VALUES (?)", (endereco_ip,))
    db.commit()


def limpar_tentativas_login(endereco_ip):
    db = get_db()
    db.execute("DELETE FROM tentativas_login WHERE endereco_ip = ?", (endereco_ip,))
    db.commit()


def quantidade_tentativas_entrega(pedido_id, endereco_ip, janela_segundos):
    """Limita tentativas do codigo de entrega mesmo em um link publico."""
    db = get_db()
    db.execute("DELETE FROM tentativas_entrega WHERE criado_em < datetime('now', '-1 day')")
    total = db.execute(
        """SELECT COUNT(*) AS total FROM tentativas_entrega
           WHERE pedido_id = ? AND endereco_ip = ?
             AND criado_em >= datetime('now', ?)""",
        (pedido_id, endereco_ip, f"-{janela_segundos} seconds"),
    ).fetchone()["total"]
    db.commit()
    return total


def registrar_tentativa_entrega(pedido_id, endereco_ip):
    db = get_db()
    db.execute(
        "INSERT INTO tentativas_entrega (pedido_id, endereco_ip) VALUES (?, ?)",
        (pedido_id, endereco_ip),
    )
    db.commit()


def limpar_tentativas_entrega(pedido_id, endereco_ip):
    db = get_db()
    db.execute(
        "DELETE FROM tentativas_entrega WHERE pedido_id = ? AND endereco_ip = ?",
        (pedido_id, endereco_ip),
    )
    db.commit()


def listar_funcionarios(estabelecimento_id):
    return get_db().execute(
        "SELECT id, nome, usuario, papel, permissoes, ativo, criado_em FROM usuarios WHERE estabelecimento_id = ? ORDER BY papel, nome COLLATE NOCASE", (estabelecimento_id,)
    ).fetchall()


def criar_usuario(nome, usuario, senha_hash, papel="FUNCIONARIO", estabelecimento_id=None, permissoes=""):
    db = get_db()
    cursor = db.execute(
        "INSERT INTO usuarios (nome, usuario, senha_hash, papel, permissoes, estabelecimento_id) VALUES (?, ?, ?, ?, ?, ?)",
        (nome, usuario, senha_hash, papel, permissoes, estabelecimento_id),
    )
    db.commit()
    return cursor.lastrowid


def definir_usuario_ativo(usuario_id, estabelecimento_id, ativo):
    """Desativa ou reativa somente contas de funcionario, sem apagar historico."""
    db = get_db()
    cursor = db.execute(
        """UPDATE usuarios SET ativo = ?
           WHERE id = ? AND estabelecimento_id = ? AND papel = 'FUNCIONARIO'""",
        (int(bool(ativo)), usuario_id, estabelecimento_id),
    )
    db.commit()
    return cursor.rowcount == 1


def obter_funcionario(usuario_id, estabelecimento_id):
    return get_db().execute(
        """SELECT id, nome, usuario, papel, permissoes, ativo, criado_em
           FROM usuarios
           WHERE id = ? AND estabelecimento_id = ? AND papel = 'FUNCIONARIO'""",
        (usuario_id, estabelecimento_id),
    ).fetchone()


def atualizar_funcionario(usuario_id, estabelecimento_id, nome, usuario, permissoes, senha_hash=None):
    """Edita dados e permissoes sem permitir alterar a conta do dono."""
    db = get_db()
    campos = ["nome = ?", "usuario = ?", "permissoes = ?"]
    valores = [nome, usuario, permissoes]
    if senha_hash:
        campos.append("senha_hash = ?")
        valores.append(senha_hash)
    valores.extend([usuario_id, estabelecimento_id])
    cursor = db.execute(
        f"""UPDATE usuarios SET {', '.join(campos)}
            WHERE id = ? AND estabelecimento_id = ? AND papel = 'FUNCIONARIO'""",
        valores,
    )
    db.commit()
    return cursor.rowcount == 1


def existe_dono():
    return get_db().execute("SELECT 1 FROM usuarios WHERE papel = 'DONO' LIMIT 1").fetchone() is not None
