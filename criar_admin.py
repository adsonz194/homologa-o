"""Cria exclusivamente o primeiro dono por acesso local ao servidor.

Este arquivo nao cria nenhuma rota web. Depois que um dono existe, ele encerra
sem alterar usuarios; os demais acessos devem ser gerenciados dentro do painel.
"""

from getpass import getpass
import re
import sqlite3

from werkzeug.security import generate_password_hash

from app import app
from database import get_db
from models import email_recuperacao_valido, existe_dono, obter_estabelecimento_por_slug


def main():
    with app.app_context():
        if existe_dono():
            print("Ja existe um dono cadastrado. Entre no painel para criar funcionarios.")
            return
        nome = input("Nome do dono: ").strip()
        usuario = input("Usuario para entrar: ").strip()
        email_recuperacao = input("E-mail para recuperar a senha: ").strip().lower()
        senha = getpass("Senha (minimo 8 caracteres): ")
        confirmacao = getpass("Repita a senha: ")
        if not nome or not re.fullmatch(r"[A-Za-z0-9_.-]{3,50}", usuario) or not email_recuperacao_valido(email_recuperacao):
            print("Nome, usuario ou e-mail invalidos. O usuario deve ter 3 a 50 letras, numeros, ponto, hifen ou sublinhado.")
            return
        if len(senha) < 12 or senha != confirmacao:
            print("Use uma senha de pelo menos 12 caracteres e confirme-a corretamente.")
            return
        try:
            estabelecimento = obter_estabelecimento_por_slug(app.config["ESTABELECIMENTO_PADRAO_SLUG"])
            get_db().execute(
                """INSERT INTO usuarios (nome, usuario, email_recuperacao, senha_hash, papel, estabelecimento_id)
                   VALUES (?, ?, ?, ?, 'DONO', ?)""",
                (nome, usuario, email_recuperacao, generate_password_hash(senha), estabelecimento["id"]),
            )
            get_db().commit()
        except sqlite3.IntegrityError:
            print("Este usuario ja esta em uso.")
            return
        print(f"Dono criado. Acesse {app.config['BASE_URL']}/entrar")


if __name__ == "__main__":
    main()
