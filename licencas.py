"""Certificados de licenca assinados para o Sistema de Delivery.

O certificado e um texto que pode ser enviado pelo WhatsApp. Ele contem a
identificacao publica da instalacao e a data de vencimento, protegidas por
uma assinatura HMAC. Alterar a data ou tentar reutilizar o certificado em
outra instalacao invalida a assinatura.
"""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from datetime import date


PREFIXO_CERTIFICADO = "MDS-LIC1"


def gerar_identificador_instalacao():
    """Gera um identificador publico, mas dificil de adivinhar, da instalacao."""
    return f"MDS-{secrets.token_hex(8).upper()}"


def _decodificar(valor):
    preenchimento = "=" * (-len(valor) % 4)
    return base64.b64decode((valor + preenchimento).encode("ascii"), altchars=b"-_", validate=True)


def _chave(chave_assinatura):
    if not isinstance(chave_assinatura, str) or len(chave_assinatura.strip()) < 32:
        raise ValueError("A chave de assinatura do certificado precisa ter pelo menos 32 caracteres.")
    return chave_assinatura.strip().encode("utf-8")


def validar_certificado(certificado, identificador_instalacao, chave_assinatura, hoje=None):
    """Valida assinatura, instalacao e vencimento sem confiar em dados do banco."""
    resultado = {"valido": False, "status": "INVALIDO", "mensagem": "Certificado invalido."}
    try:
        chave = _chave(chave_assinatura)
        prefixo, carga_codificada, assinatura_codificada = str(certificado or "").strip().split(".")
        if prefixo != PREFIXO_CERTIFICADO:
            return resultado
        assinatura_esperada = hmac.new(
            chave, carga_codificada.encode("ascii"), hashlib.sha256
        ).digest()
        assinatura_recebida = _decodificar(assinatura_codificada)
        if not hmac.compare_digest(assinatura_recebida, assinatura_esperada):
            return resultado
        carga = json.loads(_decodificar(carga_codificada).decode("utf-8"))
        campos = {"v", "instalacao", "emitido_em", "expira_em", "id"}
        if not isinstance(carga, dict) or set(carga) != campos or carga["v"] != 1:
            return resultado
        if not hmac.compare_digest(
            str(carga["instalacao"]).upper(), str(identificador_instalacao or "").strip().upper()
        ):
            return {"valido": False, "status": "OUTRA_INSTALACAO", "mensagem": "Este certificado pertence a outra instalacao."}
        expira_em = date.fromisoformat(str(carga["expira_em"]))
        emitido_em = date.fromisoformat(str(carga["emitido_em"]))
        if emitido_em > expira_em:
            return resultado
        hoje = hoje or date.today()
        if hoje > expira_em:
            return {
                "valido": False,
                "status": "EXPIRADO",
                "mensagem": f"O certificado venceu em {expira_em.strftime('%d/%m/%Y')}.",
                "expira_em": expira_em,
            }
        return {
            "valido": True,
            "status": "ATIVO",
            "mensagem": f"Licenca ativa ate {expira_em.strftime('%d/%m/%Y')}.",
            "expira_em": expira_em,
            "emitido_em": emitido_em,
            "certificado_id": str(carga["id"]),
        }
    except (AttributeError, ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        return resultado
