"""Redefine a senha do dono somente pelo terminal do servidor.

Use este recurso apenas depois de conferir os dados cadastrais da loja com a
pessoa que solicitou o atendimento. Ele nao cria rota web e nao deve ser usado
para funcionarios.
"""

from getpass import getpass

from werkzeug.security import generate_password_hash

from app import app
from database import get_db
from models import obter_estabelecimento_por_slug


def main():
    with app.app_context():
        estabelecimento = obter_estabelecimento_por_slug(
            app.config["ESTABELECIMENTO_PADRAO_SLUG"]
        )
        if estabelecimento is None:
            print("Estabelecimento nao encontrado.")
            return
        dono = get_db().execute(
            """SELECT id, nome, usuario FROM usuarios
               WHERE estabelecimento_id = ? AND papel = 'DONO' AND ativo = 1
               ORDER BY id LIMIT 1""",
            (estabelecimento["id"],),
        ).fetchone()
        if dono is None:
            print("Nao existe dono ativo nesta instalacao.")
            return
        print(f"Loja: {estabelecimento['nome']} | Dono: {dono['nome']} | Usuario: {dono['usuario']}")
        confirmacao = input(
            "Confirme que voce validou os dados cadastrais da loja. Digite CONFIRMAR: "
        ).strip()
        if confirmacao != "CONFIRMAR":
            print("Operacao cancelada.")
            return
        senha = getpass("Nova senha (minimo 12 caracteres): ")
        repetir = getpass("Repita a nova senha: ")
        if len(senha) < 12 or senha != repetir:
            print("A senha precisa ter ao menos 12 caracteres e as duas digitacoes devem coincidir.")
            return
        db = get_db()
        with db:
            db.execute(
                "UPDATE usuarios SET senha_hash = ? WHERE id = ?",
                (generate_password_hash(senha), dono["id"]),
            )
            db.execute(
                "UPDATE recuperacoes_senha SET usado_em = CURRENT_TIMESTAMP WHERE usuario_id = ? AND usado_em IS NULL",
                (dono["id"],),
            )
        print("Senha do dono redefinida. Oriente a pessoa a entrar e trocar a senha novamente, se desejar.")


if __name__ == "__main__":
    main()
