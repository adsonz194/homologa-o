import hmac
import secrets

from flask import Flask, abort, g, render_template, request, session
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from database import init_app as init_database
from routes.auth import auth_bp, permissoes_usuario, rota_inicial_painel
from routes.cliente import cliente_bp
from routes.pagamentos import pagamentos_bp
from routes.pedidos import pedidos_bp
from routes.produtos import produtos_bp
from routes.vendas import vendas_bp
from routes.webhook import webhook_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    ambiente_producao = app.config["BASE_URL"].startswith("https://")
    if ambiente_producao and app.config["SECRET_KEY"] == "desenvolvimento-altere-esta-chave":
        raise RuntimeError("Defina uma SECRET_KEY exclusiva no arquivo .env de producao.")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Em producao a variavel SESSION_COOKIE_SECURE deve ser true. Mantemos a
    # escolha explicita para que testes locais por http://IP:5000 funcionem.
    app.config["SESSION_COOKIE_SECURE"] = app.config["SESSION_COOKIE_SECURE"]
    if ambiente_producao and not app.config["SESSION_COOKIE_SECURE"]:
        app.logger.warning("SESSION_COOKIE_SECURE esta desativado; ative-o na VPS com HTTPS.")
    init_database(app)
    # As credenciais podem vir do ambiente do Render ou da area protegida de
    # configuracoes. A verificacao acontece depois de abrir o banco para cobrir
    # os dois casos sem gerar alertas falsos no log.
    if ambiente_producao:
        from models import obter_segredo_webhook_mercadopago, obter_token_mercadopago
        with app.app_context():
            if not obter_token_mercadopago():
                app.logger.error("Ambiente de producao sem Access Token do Mercado Pago configurado.")
            if not obter_segredo_webhook_mercadopago():
                app.logger.warning("Ambiente de producao sem assinatura secreta do webhook Mercado Pago.")
    app.register_blueprint(auth_bp)
    app.register_blueprint(cliente_bp)
    app.register_blueprint(vendas_bp)
    app.register_blueprint(pagamentos_bp)
    app.register_blueprint(pedidos_bp)
    app.register_blueprint(produtos_bp)
    app.register_blueprint(webhook_bp)

    @app.before_request
    def proteger_formularios():
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return
        if request.endpoint == "webhook.receber_webhook":
            return
        esperado = session.get("csrf_token")
        recebido = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not esperado or not recebido or not hmac.compare_digest(esperado, recebido):
            abort(400, "Formulario expirado ou invalido. Atualize a pagina e tente novamente.")

    @app.after_request
    def cabecalhos_de_seguranca(resposta):
        resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
        resposta.headers.setdefault("X-Frame-Options", "DENY")
        resposta.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resposta.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        resposta.headers.setdefault("Cache-Control", "no-store")
        resposta.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'self'; object-src 'none'; form-action 'self'; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; script-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'",
        )
        if ambiente_producao:
            resposta.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resposta

    @app.context_processor
    def disponibilizar_usuario():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        usuario = getattr(g, "usuario", None)
        return {
            "usuario": usuario,
            "permissoes_usuario": permissoes_usuario(usuario),
            "rota_inicial_painel": rota_inicial_painel(usuario),
            "csrf_token": session["csrf_token"],
        }

    @app.get("/healthz")
    def healthz():
        from database import get_db
        get_db().execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(405)
    @app.errorhandler(429)
    def erro_de_requisicao(erro):
        mensagens = {
            400: "A solicitacao expirou ou contem dados invalidos. Atualize a pagina e tente novamente.",
            403: "Voce nao tem permissao para realizar esta acao.",
            404: "A pagina ou pedido informado nao foi encontrado.",
            405: "Esta acao precisa ser iniciada pela tela correta do sistema.",
            429: "Muitas tentativas. Aguarde alguns minutos antes de tentar novamente.",
        }
        return render_template(
            "erro.html", codigo=erro.code, mensagem=mensagens.get(erro.code, "Ocorreu um erro."),
        ), erro.code

    @app.errorhandler(500)
    def erro_interno(_erro):
        return render_template(
            "erro.html", codigo=500, mensagem="Ocorreu uma falha temporaria. Tente novamente em instantes.",
        ), 500

    return app

app = create_app()
if __name__ == "__main__":
    app.run(host=app.config["HOST"], port=app.config["PORT"], debug=app.config["FLASK_DEBUG"])
