import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "desenvolvimento-altere-esta-chave")
    DATABASE = Path(os.getenv("DATABASE", str(BASE_DIR / "database.db")))
    MERCADOPAGO_PUBLIC_KEY = os.getenv("MERCADOPAGO_PUBLIC_KEY", "")
    MERCADOPAGO_ACCESS_TOKEN = os.getenv("MERCADOPAGO_ACCESS_TOKEN", "")
    BASE_URL = os.getenv("BASE_URL", "http://localhost:5000").rstrip("/")
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "5000"))
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    MERCADOPAGO_WEBHOOK_SECRET = os.getenv("MERCADOPAGO_WEBHOOK_SECRET", "")
    CONFIG_ENCRYPTION_KEY = os.getenv("CONFIG_ENCRYPTION_KEY", "")
    # Nunca coloque esta chave no Git nem a envie ao restaurante. Ela serve
    # apenas para assinar certificados de licenca emitidos pelo fornecedor.
    LICENSE_SIGNING_KEY = os.getenv("LICENSE_SIGNING_KEY", "")
    LICENSE_ENFORCEMENT = os.getenv("LICENSE_ENFORCEMENT", "false").lower() == "true"
    ESTABELECIMENTO_PADRAO_SLUG = os.getenv("ESTABELECIMENTO_PADRAO_SLUG", "menino-dos-sonhos")
    ESTABELECIMENTO_PADRAO_NOME = os.getenv("ESTABELECIMENTO_PADRAO_NOME", "Menino dos Sonhos")
    WHATSAPP_EMPRESA = "".join(caractere for caractere in os.getenv("WHATSAPP_EMPRESA", "5571992843791") if caractere.isdigit())
    LOGIN_MAX_TENTATIVAS = int(os.getenv("LOGIN_MAX_TENTATIVAS", "5"))
    LOGIN_JANELA_SEGUNDOS = int(os.getenv("LOGIN_JANELA_SEGUNDOS", "900"))
    PASSWORD_RESET_TTL_MINUTES = int(os.getenv("PASSWORD_RESET_TTL_MINUTES", "15"))
    PASSWORD_RESET_MAX_TENTATIVAS = int(os.getenv("PASSWORD_RESET_MAX_TENTATIVAS", "5"))
    PASSWORD_RESET_MAX_SOLICITACOES = int(os.getenv("PASSWORD_RESET_MAX_SOLICITACOES", "3"))
    PASSWORD_RESET_JANELA_SEGUNDOS = int(os.getenv("PASSWORD_RESET_JANELA_SEGUNDOS", "900"))
    SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "").strip()
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
    SUPPORT_WHATSAPP = "".join(caractere for caractere in os.getenv("SUPPORT_WHATSAPP", "5571992843791") if caractere.isdigit())
