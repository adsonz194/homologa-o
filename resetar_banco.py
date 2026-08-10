"""Remove os dados de demonstracao sem apagar a estrutura do sistema.

Uso:
    python resetar_banco.py --confirmar

Antes de qualquer exclusao, o script cria uma copia local do banco. Nunca
adicione essa copia ao GitHub: arquivos .db ja sao ignorados pelo .gitignore.
"""

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

from config import Config


TABELAS_COM_DADOS = (
    "pedido_itens",
    "produto_complementos",
    "pedidos",
    "vendas",
    "produtos",
    "usuarios",
    "tentativas_login",
    "recuperacoes_senha",
    "solicitacoes_recuperacao_senha",
    "locais_entrega",
    "estabelecimentos",
)


def criar_backup(conexao, caminho_banco):
    pasta_backup = caminho_banco.parent / "backups"
    pasta_backup.mkdir(exist_ok=True)
    horario = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = pasta_backup / f"database-antes-da-entrega-{horario}.db"
    with sqlite3.connect(destino) as copia:
        conexao.backup(copia)
    return destino


def resetar(caminho_banco):
    with sqlite3.connect(caminho_banco) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA wal_checkpoint(FULL)")
        backup = criar_backup(db, caminho_banco)
        with db:
            for tabela in TABELAS_COM_DADOS:
                db.execute(f"DELETE FROM {tabela}")
            db.execute(
                "INSERT INTO estabelecimentos (nome, slug, status_plano) VALUES (?, ?, 'ATIVO')",
                (Config.ESTABELECIMENTO_PADRAO_NOME, Config.ESTABELECIMENTO_PADRAO_SLUG),
            )
            try:
                db.execute(
                    "DELETE FROM sqlite_sequence WHERE name IN ({})".format(
                        ", ".join("?" for _ in TABELAS_COM_DADOS)
                    ),
                    TABELAS_COM_DADOS,
                )
            except sqlite3.OperationalError:
                # Bancos sem AUTOINCREMENT nao possuem sqlite_sequence.
                pass
    return backup


def main():
    argumentos = argparse.ArgumentParser(description="Limpa dados do SistemaVenda para entrega.")
    argumentos.add_argument(
        "--confirmar",
        action="store_true",
        help="Confirma a exclusao de usuarios, produtos, pedidos, vendas e configuracoes.",
    )
    args = argumentos.parse_args()
    if not args.confirmar:
        argumentos.error("Use --confirmar para executar a limpeza.")

    caminho_banco = Path(Config.DATABASE)
    if not caminho_banco.exists():
        raise SystemExit(f"Banco nao encontrado: {caminho_banco}")
    backup = resetar(caminho_banco)
    print("Banco limpo com sucesso. Nenhum usuario ou dado comercial permaneceu.")
    print(f"Backup local criado em: {backup}")
    print("Agora crie o primeiro dono com: python criar_admin.py")


if __name__ == "__main__":
    main()
