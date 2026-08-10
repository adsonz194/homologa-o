"""Envio de e-mails transacionais sem expor credenciais no codigo."""

import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app


class EmailEnvioErro(RuntimeError):
    """Falha segura, sem incluir host, usuario ou senha nos avisos ao usuario."""


def email_recuperacao_configurado():
    configuracao = current_app.config
    return bool(configuracao["SMTP_HOST"] and (configuracao["SMTP_FROM"] or configuracao["SMTP_USERNAME"]))


def enviar_codigo_recuperacao(destinatario, codigo, nome):
    """Envia um codigo de uso unico para a recuperacao do painel."""
    if not email_recuperacao_configurado():
        raise EmailEnvioErro("O envio de e-mail ainda nao foi configurado.")

    configuracao = current_app.config
    remetente = configuracao["SMTP_FROM"] or configuracao["SMTP_USERNAME"]
    validade = configuracao["PASSWORD_RESET_TTL_MINUTES"]
    mensagem = EmailMessage()
    mensagem["Subject"] = "Codigo para redefinir a senha - AG Delivery"
    mensagem["From"] = remetente
    mensagem["To"] = destinatario
    mensagem.set_content(
        f"Ola, {nome}.\n\n"
        f"Seu codigo para redefinir a senha do painel AG Delivery e: {codigo}\n\n"
        f"Ele vale por {validade} minutos e pode ser usado uma unica vez. "
        "Nao compartilhe este codigo com ninguem.\n\n"
        "Se voce nao solicitou esta alteracao, ignore esta mensagem."
    )
    try:
        contexto = ssl.create_default_context()
        if configuracao["SMTP_USE_SSL"]:
            servidor = smtplib.SMTP_SSL(
                configuracao["SMTP_HOST"], configuracao["SMTP_PORT"], timeout=15, context=contexto
            )
        else:
            servidor = smtplib.SMTP(configuracao["SMTP_HOST"], configuracao["SMTP_PORT"], timeout=15)
        with servidor:
            servidor.ehlo()
            if configuracao["SMTP_USE_TLS"] and not configuracao["SMTP_USE_SSL"]:
                servidor.starttls(context=contexto)
                servidor.ehlo()
            if configuracao["SMTP_USERNAME"]:
                servidor.login(configuracao["SMTP_USERNAME"], configuracao["SMTP_PASSWORD"])
            servidor.send_message(mensagem)
    except (OSError, smtplib.SMTPException) as erro:
        current_app.logger.error("Falha ao enviar codigo de recuperacao: %s", type(erro).__name__)
        raise EmailEnvioErro("Nao foi possivel enviar o e-mail agora.") from erro
