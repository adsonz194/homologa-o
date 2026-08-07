import base64
import hashlib
from datetime import datetime, time
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from database import gerar_codigo_acompanhamento, get_db


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
    estabelecimento_id, nome, whatsapp, valor_entrega, url_publica, dias_funcionamento,
    horario_abertura, horario_encerramento, access_token="", webhook_secret=""
):
    """Atualiza configuracoes da loja sem devolver credenciais ao navegador."""
    campos = [
        "nome = ?", "whatsapp = ?", "telefone = ?", "valor_entrega = ?", "url_publica = ?",
        "dias_funcionamento = ?", "horario_abertura = ?", "horario_encerramento = ?",
    ]
    valores = [nome, whatsapp, whatsapp, valor_entrega, url_publica, dias_funcionamento, horario_abertura, horario_encerramento]
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


def criar_pedido(cliente, telefone, endereco, local_entrega, modalidade_entrega, email, forma_pagamento, carrinho, estabelecimento_id):
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
        cursor = db.execute(
            """INSERT INTO pedidos
               (cliente, telefone, endereco, local_entrega, modalidade_entrega, email, forma_pagamento, valor_total, valor_entrega,
                codigo_acompanhamento, estabelecimento_id, estoque_reservado)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (cliente, telefone, endereco, local_entrega, modalidade_entrega, email, forma_pagamento, total, valor_entrega, gerar_codigo_acompanhamento(db), estabelecimento_id),
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
    return get_db().execute("SELECT * FROM pedido_itens WHERE pedido_id = ?", (pedido_id,)).fetchall()


def listar_pedidos(estabelecimento_id):
    return get_db().execute(
        """SELECT pedidos.*, GROUP_CONCAT(pedido_itens.quantidade || 'x ' || pedido_itens.descricao, ', ') AS itens
           FROM pedidos LEFT JOIN pedido_itens ON pedido_itens.pedido_id = pedidos.id
           WHERE pedidos.estabelecimento_id = ? GROUP BY pedidos.id ORDER BY pedidos.id DESC""", (estabelecimento_id,)
    ).fetchall()


def listar_pedidos_aprovados_apos(estabelecimento_id, depois_id):
    """Pedidos aprovados depois do ultimo ID visto pelo painel."""
    return get_db().execute(
        """SELECT id, cliente, valor_total, local_entrega
           FROM pedidos
           WHERE estabelecimento_id = ? AND status_pagamento = 'APROVADO' AND id > ?
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


def atualizar_pagamento_pedido(pedido_id, status, payment_id=None):
    db = get_db()
    with db:
        pedido = obter_pedido(pedido_id)
        if pedido is None:
            return
        if status == "APROVADO" and not pedido["estoque_reservado"]:
            # O carrinho e o pedido pendente nao reservam estoque. Esta atualizacao
            # condicional impede que retorno do checkout e webhook baixem duas vezes.
            baixa_confirmada = db.execute(
                "UPDATE pedidos SET estoque_reservado = 1 WHERE id = ? AND estoque_reservado = 0",
                (pedido_id,),
            ).rowcount
            if baixa_confirmada:
                for item in itens_pedido(pedido_id):
                    db.execute(
                        """UPDATE produtos SET estoque = estoque - ?
                           WHERE id = ? AND estabelecimento_id = ?""",
                        (item["quantidade"], item["produto_id"], pedido["estabelecimento_id"]),
                    )
        if status in {"REJEITADO", "CANCELADO"} and pedido["estoque_reservado"]:
            for item in itens_pedido(pedido_id):
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


def listar_funcionarios(estabelecimento_id):
    return get_db().execute(
        "SELECT id, nome, usuario, papel, ativo, criado_em FROM usuarios WHERE estabelecimento_id = ? ORDER BY papel, nome COLLATE NOCASE", (estabelecimento_id,)
    ).fetchall()


def criar_usuario(nome, usuario, senha_hash, papel="FUNCIONARIO", estabelecimento_id=None):
    db = get_db()
    cursor = db.execute(
        "INSERT INTO usuarios (nome, usuario, senha_hash, papel, estabelecimento_id) VALUES (?, ?, ?, ?, ?)",
        (nome, usuario, senha_hash, papel, estabelecimento_id),
    )
    db.commit()
    return cursor.lastrowid


def existe_dono():
    return get_db().execute("SELECT 1 FROM usuarios WHERE papel = 'DONO' LIMIT 1").fetchone() is not None
