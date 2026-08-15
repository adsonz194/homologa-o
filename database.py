import sqlite3
import secrets
from flask import current_app, g

from licencas import gerar_identificador_instalacao


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
        razao_social TEXT NOT NULL DEFAULT '',
        cnpj TEXT NOT NULL DEFAULT '',
        endereco TEXT NOT NULL DEFAULT '',
        slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
        telefone TEXT NOT NULL DEFAULT '',
        whatsapp TEXT NOT NULL DEFAULT '',
        valor_entrega REAL NOT NULL DEFAULT 6 CHECK(valor_entrega >= 0),
        url_publica TEXT NOT NULL DEFAULT '',
        dias_funcionamento TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
        horario_abertura TEXT NOT NULL DEFAULT '08:00',
        horario_encerramento TEXT NOT NULL DEFAULT '22:00',
        fechado_hoje_data TEXT,
        mercadopago_token_criptografado TEXT,
        mercadopago_point_token_criptografado TEXT,
        mercadopago_point_terminal_id TEXT NOT NULL DEFAULT '',
        webhook_secret_criptografado TEXT,
        identificador_instalacao TEXT,
        certificado_licenca_criptografado TEXT,
        certificado_ativado_em TEXT,
        certificado_expira_em TEXT,
        status_plano TEXT NOT NULL DEFAULT 'ATIVO' CHECK(status_plano IN ('PENDENTE', 'ATIVO', 'EXPIRADO', 'CANCELADO')),
        plano_expira_em TEXT,
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS vendas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, cliente TEXT NOT NULL, produto TEXT NOT NULL,
        quantidade INTEGER NOT NULL CHECK(quantidade > 0), valor_unitario REAL NOT NULL CHECK(valor_unitario >= 0),
        desconto REAL NOT NULL DEFAULT 0 CHECK(desconto >= 0), valor_total REAL NOT NULL,
        forma_pagamento TEXT NOT NULL, status_pagamento TEXT NOT NULL DEFAULT 'PENDENTE',
        preference_id TEXT, payment_id TEXT, point_order_id TEXT,
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    db.execute("""CREATE TABLE IF NOT EXISTS produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo_interno TEXT NOT NULL UNIQUE,
        ean TEXT UNIQUE,
        descricao TEXT NOT NULL,
        valor_unitario REAL NOT NULL CHECK(valor_unitario > 0),
        categoria TEXT NOT NULL DEFAULT 'Geral',
        imagem_url TEXT NOT NULL DEFAULT '',
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS produto_complementos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER NOT NULL,
        descricao TEXT NOT NULL,
        valor_adicional REAL NOT NULL DEFAULT 0 CHECK(valor_adicional >= 0),
        ativo INTEGER NOT NULL DEFAULT 1,
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(produto_id) REFERENCES produtos(id) ON DELETE CASCADE
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        usuario TEXT NOT NULL UNIQUE COLLATE NOCASE,
        email_recuperacao TEXT NOT NULL DEFAULT '',
        senha_hash TEXT NOT NULL,
        papel TEXT NOT NULL CHECK(papel IN ('DONO', 'FUNCIONARIO')),
        permissoes TEXT NOT NULL DEFAULT '',
        ativo INTEGER NOT NULL DEFAULT 1,
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS tentativas_login (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endereco_ip TEXT NOT NULL,
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS recuperacoes_senha (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        codigo_hash TEXT NOT NULL,
        expira_em TEXT NOT NULL,
        tentativas INTEGER NOT NULL DEFAULT 0,
        usado_em TEXT,
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS solicitacoes_recuperacao_senha (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endereco_ip TEXT NOT NULL,
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS pedidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente TEXT NOT NULL,
        telefone TEXT NOT NULL,
        endereco TEXT NOT NULL,
        local_entrega TEXT NOT NULL DEFAULT '',
        modalidade_entrega TEXT NOT NULL DEFAULT 'ENTREGA',
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
        valor_entrega REAL NOT NULL DEFAULT 0,
        valor_recebido REAL,
        troco REAL NOT NULL DEFAULT 0,
        codigo_acompanhamento TEXT,
        codigo_entrega TEXT,
        entregue_em TEXT,
        observacao TEXT NOT NULL DEFAULT '',
        agendado_para TEXT,
        prazo_entrega_minutos INTEGER,
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
    db.execute("""CREATE TABLE IF NOT EXISTS tentativas_entrega (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pedido_id INTEGER NOT NULL,
        endereco_ip TEXT NOT NULL,
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(pedido_id) REFERENCES pedidos(id) ON DELETE CASCADE
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS locais_entrega (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        estabelecimento_id INTEGER NOT NULL,
        nome TEXT NOT NULL,
        horario_abertura TEXT NOT NULL DEFAULT '00:00',
        horario_encerramento TEXT NOT NULL,
        valor_entrega REAL NOT NULL DEFAULT 0 CHECK(valor_entrega >= 0),
        pedido_minimo REAL NOT NULL DEFAULT 0 CHECK(pedido_minimo >= 0),
        prazo_estimado_minutos INTEGER NOT NULL DEFAULT 45 CHECK(prazo_estimado_minutos BETWEEN 5 AND 360),
        ativo INTEGER NOT NULL DEFAULT 1 CHECK(ativo IN (0, 1)),
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(estabelecimento_id) REFERENCES estabelecimentos(id) ON DELETE CASCADE,
        UNIQUE(estabelecimento_id, nome COLLATE NOCASE)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS auditoria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        estabelecimento_id INTEGER NOT NULL,
        usuario_id INTEGER,
        usuario_nome TEXT NOT NULL DEFAULT '',
        acao TEXT NOT NULL,
        recurso TEXT NOT NULL DEFAULT '',
        recurso_id INTEGER,
        detalhe TEXT NOT NULL DEFAULT '',
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(estabelecimento_id) REFERENCES estabelecimentos(id) ON DELETE CASCADE,
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
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
    if "dias_funcionamento" not in colunas_estabelecimentos:
        db.execute(
            "ALTER TABLE estabelecimentos ADD COLUMN dias_funcionamento TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6'"
        )
    if "horario_abertura" not in colunas_estabelecimentos:
        db.execute(
            "ALTER TABLE estabelecimentos ADD COLUMN horario_abertura TEXT NOT NULL DEFAULT '08:00'"
        )
    if "horario_encerramento" not in colunas_estabelecimentos:
        db.execute(
            "ALTER TABLE estabelecimentos ADD COLUMN horario_encerramento TEXT NOT NULL DEFAULT '22:00'"
        )
    if "fechado_hoje_data" not in colunas_estabelecimentos:
        db.execute("ALTER TABLE estabelecimentos ADD COLUMN fechado_hoje_data TEXT")
    if "mercadopago_point_token_criptografado" not in colunas_estabelecimentos:
        db.execute("ALTER TABLE estabelecimentos ADD COLUMN mercadopago_point_token_criptografado TEXT")
    if "mercadopago_point_terminal_id" not in colunas_estabelecimentos:
        db.execute("ALTER TABLE estabelecimentos ADD COLUMN mercadopago_point_terminal_id TEXT NOT NULL DEFAULT ''")
    if "razao_social" not in colunas_estabelecimentos:
        db.execute("ALTER TABLE estabelecimentos ADD COLUMN razao_social TEXT NOT NULL DEFAULT ''")
    if "cnpj" not in colunas_estabelecimentos:
        db.execute("ALTER TABLE estabelecimentos ADD COLUMN cnpj TEXT NOT NULL DEFAULT ''")
    if "endereco" not in colunas_estabelecimentos:
        db.execute("ALTER TABLE estabelecimentos ADD COLUMN endereco TEXT NOT NULL DEFAULT ''")
    if "identificador_instalacao" not in colunas_estabelecimentos:
        db.execute("ALTER TABLE estabelecimentos ADD COLUMN identificador_instalacao TEXT")
    if "certificado_licenca_criptografado" not in colunas_estabelecimentos:
        db.execute("ALTER TABLE estabelecimentos ADD COLUMN certificado_licenca_criptografado TEXT")
    if "certificado_ativado_em" not in colunas_estabelecimentos:
        db.execute("ALTER TABLE estabelecimentos ADD COLUMN certificado_ativado_em TEXT")
    if "certificado_expira_em" not in colunas_estabelecimentos:
        db.execute("ALTER TABLE estabelecimentos ADD COLUMN certificado_expira_em TEXT")
    instalacoes_sem_codigo = db.execute(
        "SELECT id FROM estabelecimentos WHERE identificador_instalacao IS NULL OR identificador_instalacao = ''"
    ).fetchall()
    for instalacao in instalacoes_sem_codigo:
        db.execute(
            "UPDATE estabelecimentos SET identificador_instalacao = ? WHERE id = ?",
            (gerar_identificador_instalacao(), instalacao["id"]),
        )
    # Mantem os locais que ja existiam no delivery anterior. A partir desta
    # migracao, eles passam a ser editaveis pelo dono no painel.
    locais_existentes = db.execute(
        "SELECT COUNT(*) AS total FROM locais_entrega WHERE estabelecimento_id = ?",
        (estabelecimento_padrao_id,),
    ).fetchone()["total"]
    if locais_existentes == 0 and current_app.config["ESTABELECIMENTO_PADRAO_SLUG"] == "menino-dos-sonhos":
        db.executemany(
            """INSERT INTO locais_entrega (estabelecimento_id, nome, horario_abertura, horario_encerramento)
               VALUES (?, ?, ?, ?)""",
            (
                (estabelecimento_padrao_id, "Imbassai", "00:00", "00:00"),
                (estabelecimento_padrao_id, "Marbelo", "00:00", "00:00"),
                (estabelecimento_padrao_id, "Marasu", "00:00", "20:00"),
            ),
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
    if "point_order_id" not in colunas_vendas:
        db.execute("ALTER TABLE vendas ADD COLUMN point_order_id TEXT")
    colunas_produtos = {coluna["name"] for coluna in db.execute("PRAGMA table_info(produtos)")}
    if "disponivel" not in colunas_produtos:
        db.execute("ALTER TABLE produtos ADD COLUMN disponivel INTEGER NOT NULL DEFAULT 1")
    if "estoque" not in colunas_produtos:
        db.execute("ALTER TABLE produtos ADD COLUMN estoque INTEGER NOT NULL DEFAULT 0")
    if "estabelecimento_id" not in colunas_produtos:
        db.execute("ALTER TABLE produtos ADD COLUMN estabelecimento_id INTEGER")
    if "categoria" not in colunas_produtos:
        db.execute("ALTER TABLE produtos ADD COLUMN categoria TEXT NOT NULL DEFAULT 'Geral'")
    if "imagem_url" not in colunas_produtos:
        db.execute("ALTER TABLE produtos ADD COLUMN imagem_url TEXT NOT NULL DEFAULT ''")
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
    if "local_entrega" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN local_entrega TEXT NOT NULL DEFAULT ''")
    if "modalidade_entrega" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN modalidade_entrega TEXT NOT NULL DEFAULT 'ENTREGA'")
    if "estabelecimento_id" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN estabelecimento_id INTEGER")
    if "valor_recebido" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN valor_recebido REAL")
    if "troco" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN troco REAL NOT NULL DEFAULT 0")
    if "codigo_entrega" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN codigo_entrega TEXT")
    if "entregue_em" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN entregue_em TEXT")
    if "observacao" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN observacao TEXT NOT NULL DEFAULT ''")
    if "agendado_para" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN agendado_para TEXT")
    if "prazo_entrega_minutos" not in colunas_pedidos:
        db.execute("ALTER TABLE pedidos ADD COLUMN prazo_entrega_minutos INTEGER")
    colunas_usuarios = {coluna["name"] for coluna in db.execute("PRAGMA table_info(usuarios)")}
    if "estabelecimento_id" not in colunas_usuarios:
        db.execute("ALTER TABLE usuarios ADD COLUMN estabelecimento_id INTEGER")
    if "permissoes" not in colunas_usuarios:
        db.execute("ALTER TABLE usuarios ADD COLUMN permissoes TEXT NOT NULL DEFAULT ''")
    if "email_recuperacao" not in colunas_usuarios:
        db.execute("ALTER TABLE usuarios ADD COLUMN email_recuperacao TEXT NOT NULL DEFAULT ''")
    colunas_locais_entrega = {
        coluna["name"] for coluna in db.execute("PRAGMA table_info(locais_entrega)")
    }
    if "horario_abertura" not in colunas_locais_entrega:
        db.execute("ALTER TABLE locais_entrega ADD COLUMN horario_abertura TEXT NOT NULL DEFAULT '00:00'")
    if "valor_entrega" not in colunas_locais_entrega:
        db.execute("ALTER TABLE locais_entrega ADD COLUMN valor_entrega REAL NOT NULL DEFAULT 0")
        db.execute(
            """UPDATE locais_entrega
               SET valor_entrega = COALESCE((
                    SELECT valor_entrega FROM estabelecimentos
                    WHERE estabelecimentos.id = locais_entrega.estabelecimento_id
               ), 0)"""
        )
    if "pedido_minimo" not in colunas_locais_entrega:
        db.execute("ALTER TABLE locais_entrega ADD COLUMN pedido_minimo REAL NOT NULL DEFAULT 0")
    if "prazo_estimado_minutos" not in colunas_locais_entrega:
        db.execute("ALTER TABLE locais_entrega ADD COLUMN prazo_estimado_minutos INTEGER NOT NULL DEFAULT 45")
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
    db.execute("CREATE INDEX IF NOT EXISTS idx_produto_complementos_produto ON produto_complementos(produto_id, ativo)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_vendas_estabelecimento ON vendas(estabelecimento_id, id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_vendas_point_order ON vendas(point_order_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_pedidos_estabelecimento ON pedidos(estabelecimento_id, id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_usuarios_estabelecimento ON usuarios(estabelecimento_id, usuario)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tentativas_login_ip_data ON tentativas_login(endereco_ip, criado_em)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_recuperacoes_senha_usuario_data ON recuperacoes_senha(usuario_id, criado_em)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_solicitacoes_recuperacao_ip_data ON solicitacoes_recuperacao_senha(endereco_ip, criado_em)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tentativas_entrega_pedido_ip_data ON tentativas_entrega(pedido_id, endereco_ip, criado_em)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_locais_entrega_estabelecimento ON locais_entrega(estabelecimento_id, ativo, nome)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_auditoria_estabelecimento_data ON auditoria(estabelecimento_id, id DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_produtos_categoria ON produtos(estabelecimento_id, categoria, descricao)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_pedidos_agendado ON pedidos(estabelecimento_id, agendado_para)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pedidos_codigo_acompanhamento ON pedidos(codigo_acompanhamento)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_estabelecimentos_instalacao ON estabelecimentos(identificador_instalacao)")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_email_recuperacao
                  ON usuarios(email_recuperacao COLLATE NOCASE)
                  WHERE email_recuperacao <> ''""")
    db.commit()

def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
