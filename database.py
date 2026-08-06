import sqlite3
import secrets
from flask import current_app, g


def gerar_codigo_acompanhamento(db):
    for _ in range(20):
        # 64 bits aleat\u00f3rios tornam invi\u00e1vel adivinhar o link de outro pedido.
        codigo = f"MDS-{secrets.token_hex(8).upper()}"
        existe = db.execute(
            "SELECT 1 FROM pedidos WHERE codigo_acompanhamento = ?", (codigo,)
        ).fetchone()
        if existe is None:
            return codigo
    raise RuntimeError("Nao foi possivel gerar um codigo de acompanhamento unico.")

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 15000")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db

def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    db.execute("""CREATE TABLE IF NOT EXISTS estabelecimentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
        telefone TEXT NOT NULL DEFAULT '',
        whatsapp TEXT NOT NULL DEFAULT '',
        valor_entrega REAL NOT NULL DEFAULT 6 CHECK(valor_entrega >= 0),
        url_publica TEXT NOT NULL DEFAULT '',
        mercadopago_token_criptografado TEXT,
        webhook_secret_criptografado TEXT,
        status_plano TEXT NOT NULL DEFAULT 'ATIVO' CHECK(status_plano IN ('PENDENTE', 'ATIVO', 'EXPIRADO', 'CANCELADO')),
        plano_expira_em TEXT,
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS vendas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, cliente TEXT NOT NULL, produto TEXT NOT NULL,
        quantidade INTEGER NOT NULL CHECK(quantidade > 0), valor_unitario REAL NOT NULL CHECK(valor_unitario >= 0),
        desconto REAL NOT NULL DEFAULT 0 CHECK(desconto >= 0), valor_total REAL NOT NULL,
        forma_pagamento TEXT NOT NULL, status_pagamento TEXT NOT NULL DEFAULT 'PENDENTE',
        preference_id TEXT, payment_id TEXT, criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    db.execute("""CREATE TABLE IF NOT EXISTS produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo_interno TEXT NOT NULL UNIQUE,
        ean TEXT UNIQUE,
        descricao TEXT NOT NULL,
        valor_unitario REAL NOT NULL CHECK(valor_unitario > 0),
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        usuario TEXT NOT NULL UNIQUE COLLATE NOCASE,
        senha_hash TEXT NOT NULL,
        papel TEXT NOT NULL CHECK(papel IN ('DONO', 'FUNCIONARIO')),
        ativo INTEGER NOT NULL DEFAULT 1,
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS tentativas_login (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endereco_ip TEXT NOT NULL,
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS pedidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente TEXT NOT NULL,
        telefone TEXT NOT NULL,
        endereco TEXT NOT NULL,
        forma_pagamento TEXT NOT NULL,
        status_pagamento TEXT NOT NULL DEFAULT 'PENDENTE',
        status_operacional TEXT NOT NULL DEFAULT 'PENDENTE',
        valor_total REAL NOT NULL,
        preference_id TEXT,
        payment_id TEXT,
        mercadopago_order_id TEXT,
        email TEXT NOT NULL DEFAULT '',
        pix_qr_code TEXT,
        pix_qr_code_base64 TEXT,
        estoque_reservado INTEGER NOT NULL DEFAULT 0,
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS pedido_itens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pedido_id INTEGER NOT NULL,
        produto_id INTEGER NOT NULL,
        descricao TEXT NOT NULL,
        quantidade INTEGER NOT NULL CHECK(quantidade > 0),
        valor_unitario REAL NOT NULL,
        FOREIGN KEY(pedido_id) REFERENCES pedidos(id),
        FOREIGN KEY(produto_id) REFERENCES produtos(id)
    )""")
    estabelecimento_padrao = db.execute(
        "SELECT id FROM estabelecimentos WHERE slug = ? COLLATE NOCASE",
        (current_app.config["ESTABELECIMENTO_PADRAO_SLUG"],),
    ).fetchone()
    if estabelecimento_padrao is None:
        cursor = db.execute(
            """INSERT INTO estabelecimentos (nome, slug, status_plano)
               VALUES (?, ?, 'ATIVO')""",
            (
                current_app.config["ESTABELECIMENTO_PADRAO_NOME"],
                current_app.config["ESTABELECIMENTO_PADRAO_SLUG"],
            ),
        )
        estabelecimento_padrao_id = cursor.lastrowid
    else:
        estabelecimento_padrao_id = estabelecimento_padrao["id"]
    colunas_estabelecimentos = {
        coluna["name"] for coluna in db.execute("PRAGMA table_info(estabelecimentos)")
    }
    if "url_publica" not in colunas_estabelecimentos:
        db.execute("ALTER TABLE estabelecimentos ADD COLUMN url_publica TEXT NOT NULL DEFAULT ''")
        # Migracao unica da base anterior, cuja taxa padrao era zero. Depois
        # disso, o dono pode inclusive configurar entrega gratuita (R$ 0,00).
        db.execute(
            "UPDATE estabelecimentos SET valor_entrega = 6 WHERE id = ? AND valor_entrega = 0",
            (estabelecimento_padrao_id,),
        )
    colunas_vendas = {coluna["name"] for coluna in db.execute("PRAGMA table_info(vendas)")}
    if "produto_id" not in colunas_vendas:
        db.execute("ALTER TABLE vendas ADD COLUMN produto_id INTEGER")
    if "canal_venda" not in colunas_vendas:
        db.execute("ALTER TABLE vendas ADD COLUMN canal_venda TEXT NOT NULL DEFAULT 'INTERNA'")
    if "estoque_reservado" not in colunas_vendas:
        db.execute("ALTER TABLE vendas ADD COLUMN estoque_reservado INTEGER NOT NULL DEFAULT 0")
    if "estabelecimento_id" not in colunas_vendas:
        db.execute("ALTER TABLE vendas ADD COLUMN estabelecimento_id INTEGER")
    colunas_produtos = {coluna["name"] for coluna in db.execute("PRAGMA table_info(produtos)")}
    if "disponivel" not in colunas_produtos:
        db.execute("ALTER TABLE produtos ADD COLUMN disponivel INTEGER NOT NULL DEFAULT 1")
    if "estoque" not in colunas_produtos:
        db.execute("ALTER TABLE produtos ADD COLUMN estoque INTEGER NOT NULL DEFAULT 0")
    if "estabelecimento_id" not in colunas_produtos:
        db.execute("ALTER TABLE produtos ADD COLUMN estabelecimento_id INTEGER")
    colunas_pedidos = {coluna["name"] for coluna in db.execute("PRAGMA table_info(pedidos)")}
    if "status_operacional" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN status_operacional TEXT NOT NULL DEFAULT 'PENDENTE'")
    if "mercadopago_order_id" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN mercadopago_order_id TEXT")
    if "email" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN email TEXT NOT NULL DEFAULT ''")
    if "pix_qr_code" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN pix_qr_code TEXT")
    if "pix_qr_code_base64" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN pix_qr_code_base64 TEXT")
    if "codigo_acompanhamento" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN codigo_acompanhamento TEXT")
    if "valor_entrega" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN valor_entrega REAL NOT NULL DEFAULT 0")
    if "estabelecimento_id" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN estabelecimento_id INTEGER")
    colunas_usuarios = {coluna["name"] for coluna in db.execute("PRAGMA table_info(usuarios)")}
    if "estabelecimento_id" not in colunas_usuarios:
        db.execute("ALTER TABLE usuarios ADD COLUMN estabelecimento_id INTEGER")
    for tabela in ("vendas", "produtos", "pedidos", "usuarios"):
        db.execute(
            f"UPDATE {tabela} SET estabelecimento_id = ? WHERE estabelecimento_id IS NULL",
            (estabelecimento_padrao_id,),
        )
    pedidos_sem_codigo = db.execute(
        "SELECT id FROM pedidos WHERE codigo_acompanhamento IS NULL OR codigo_acompanhamento = ''"
    ).fetchall()
    for pedido in pedidos_sem_codigo:
        db.execute(
            "UPDATE pedidos SET codigo_acompanhamento = ? WHERE id = ?",
            (gerar_codigo_acompanhamento(db), pedido["id"]),
        )
    db.execute("CREATE INDEX IF NOT EXISTS idx_produtos_descricao ON produtos(descricao)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_produtos_estabelecimento ON produtos(estabelecimento_id, descricao)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_vendas_estabelecimento ON vendas(estabelecimento_id, id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_pedidos_estabelecimento ON pedidos(estabelecimento_id, id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_usuarios_estabelecimento ON usuarios(estabelecimento_id, usuario)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tentativas_login_ip_data ON tentativas_login(endereco_ip, criado_em)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pedidos_codigo_acompanhamento ON pedidos(codigo_acompanhamento)")
    db.commit()

def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
