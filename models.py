from database import gerar_codigo_acompanhamento, get_db


class EstoqueInsuficiente(ValueError):
    pass


def obter_estabelecimento(estabelecimento_id):
    """Compatibilidade com a base existente: a interface usa somente a loja principal."""
    return get_db().execute(
        "SELECT * FROM estabelecimentos WHERE id = ?", (estabelecimento_id,)
    ).fetchone()


def obter_estabelecimento_por_slug(slug):
    return get_db().execute(
        "SELECT * FROM estabelecimentos WHERE slug = ? COLLATE NOCASE", (slug,)
    ).fetchone()


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
    for produto_id, quantidade in carrinho.items():
        try:
            produto = obter_produto(int(produto_id), estabelecimento_id)
            quantidade = int(quantidade)
        except (TypeError, ValueError):
            continue
        if produto is not None and quantidade > 0:
            itens.append({"produto": produto, "quantidade": quantidade, "subtotal": produto["valor_unitario"] * quantidade})
    return itens


def criar_pedido(cliente, telefone, endereco, email, forma_pagamento, carrinho, estabelecimento_id):
    itens = detalhes_carrinho(carrinho, estabelecimento_id)
    if not itens:
        raise EstoqueInsuficiente("Carrinho vazio.")
    estabelecimento = obter_estabelecimento(estabelecimento_id)
    if estabelecimento is None:
        raise EstoqueInsuficiente("Estabelecimento indisponivel.")
    db = get_db()
    with db:
        valor_entrega = estabelecimento["valor_entrega"]
        total = valor_entrega
        for item in itens:
            produto = db.execute("SELECT * FROM produtos WHERE id = ? AND estabelecimento_id = ?", (item["produto"]["id"], estabelecimento_id)).fetchone()
            if produto is None or not produto["disponivel"] or produto["estoque"] < item["quantidade"]:
                raise EstoqueInsuficiente(f"{item['produto']['descricao']} nao possui estoque suficiente.")
            item["produto"] = produto
            item["subtotal"] = produto["valor_unitario"] * item["quantidade"]
            total += item["subtotal"]
        cursor = db.execute(
            """INSERT INTO pedidos
               (cliente, telefone, endereco, email, forma_pagamento, valor_total, valor_entrega,
                codigo_acompanhamento, estabelecimento_id, estoque_reservado)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (cliente, telefone, endereco, email, forma_pagamento, total, valor_entrega, gerar_codigo_acompanhamento(db), estabelecimento_id),
        )
        pedido_id = cursor.lastrowid
        for item in itens:
            produto = item["produto"]
            db.execute(
                """INSERT INTO pedido_itens (pedido_id, produto_id, descricao, quantidade, valor_unitario)
                   VALUES (?, ?, ?, ?, ?)""",
                (pedido_id, produto["id"], produto["descricao"], item["quantidade"], produto["valor_unitario"]),
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
