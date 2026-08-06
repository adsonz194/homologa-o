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
    ESTABELECIMENTO_PADRAO_SLUG = os.getenv("ESTABELECIMENTO_PADRAO_SLUG", "menino-dos-sonhos")
    ESTABELECIMENTO_PADRAO_NOME = os.getenv("ESTABELECIMENTO_PADRAO_NOME", "Menino dos Sonhos")
    WHATSAPP_EMPRESA = "".join(caractere for caractere in os.getenv("WHATSAPP_EMPRESA", "5571992843791") if caractere.isdigit())
    LOGIN_MAX_TENTATIVAS = int(os.getenv("LOGIN_MAX_TENTATIVAS", "5"))
    LOGIN_JANELA_SEGUNDOS = int(os.getenv("LOGIN_JANELA_SEGUNDOS", "900"))
