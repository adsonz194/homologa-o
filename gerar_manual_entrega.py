"""Gera o manual de entrega e ativacao em PDF."""

from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


RAIZ = Path(__file__).resolve().parent
ARQUIVO_SAIDA = RAIZ / "output" / "pdf" / "Manual_de_Entrega_e_Ativacao.pdf"
VERMELHO = colors.HexColor("#E51B2B")
VINHO = colors.HexColor("#9F0D1A")
TEXTO = colors.HexColor("#252525")
CINZA = colors.HexColor("#6B7280")
FUNDO = colors.HexColor("#FFF5F5")


def estilos():
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle(
            "TituloManual", parent=base["Title"], fontName="Helvetica-Bold", fontSize=27,
            leading=32, textColor=TEXTO, alignment=TA_LEFT, spaceAfter=11,
        ),
        "subtitulo": ParagraphStyle(
            "SubtituloManual", parent=base["Normal"], fontName="Helvetica", fontSize=12,
            leading=18, textColor=CINZA, spaceAfter=18,
        ),
        "h1": ParagraphStyle(
            "ManualH1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=17,
            leading=22, textColor=TEXTO, spaceBefore=6, spaceAfter=9,
        ),
        "h2": ParagraphStyle(
            "ManualH2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11.5,
            leading=16, textColor=VINHO, spaceBefore=9, spaceAfter=5,
        ),
        "texto": ParagraphStyle(
            "ManualTexto", parent=base["BodyText"], fontName="Helvetica", fontSize=9.4,
            leading=14, textColor=TEXTO, spaceAfter=7,
        ),
        "nota": ParagraphStyle(
            "ManualNota", parent=base["BodyText"], fontName="Helvetica", fontSize=8.7,
            leading=12.5, textColor=TEXTO, leftIndent=8, rightIndent=8, spaceAfter=8,
        ),
        "lista": ParagraphStyle(
            "ManualLista", parent=base["BodyText"], fontName="Helvetica", fontSize=9.3,
            leading=13.5, textColor=TEXTO, leftIndent=15, firstLineIndent=-9, spaceAfter=3,
        ),
        "codigo": ParagraphStyle(
            "ManualCodigo", parent=base["Code"], fontName="Courier", fontSize=8.5,
            leading=11.5, textColor=colors.HexColor("#1F2937"),
        ),
        "rodape": ParagraphStyle(
            "Rodape", parent=base["Normal"], fontName="Helvetica", fontSize=7.5,
            textColor=CINZA, alignment=TA_CENTER,
        ),
    }


E = estilos()


def p(texto, estilo="texto"):
    return Paragraph(texto, E[estilo])


def lista(textos):
    return [p(f"- {escape(texto)}", "lista") for texto in textos]


def codigo(texto):
    return KeepTogether([
        Spacer(1, 2),
        Preformatted(texto.strip(), E["codigo"]),
        Spacer(1, 5),
    ])


def aviso(texto):
    tabela = Table([[Paragraph(f"<b>Importante:</b> {escape(texto)}", E["nota"])]], colWidths=[17.3 * cm])
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), FUNDO),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#F5B8BF")),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return tabela


def cabecalho_rodape(canvas, documento):
    canvas.saveState()
    largura, altura = A4
    canvas.setFillColor(VERMELHO)
    canvas.rect(0, altura - 0.48 * cm, largura, 0.48 * cm, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 7.5)
    canvas.setFillColor(CINZA)
    canvas.drawString(1.7 * cm, 1.15 * cm, "Menino dos Sonhos - Manual de entrega e ativacao")
    canvas.drawRightString(largura - 1.7 * cm, 1.15 * cm, f"Pagina {documento.page}")
    canvas.restoreState()


def gerar():
    ARQUIVO_SAIDA.parent.mkdir(parents=True, exist_ok=True)
    documento = SimpleDocTemplate(
        str(ARQUIVO_SAIDA), pagesize=A4, rightMargin=1.7 * cm, leftMargin=1.7 * cm,
        topMargin=1.65 * cm, bottomMargin=1.65 * cm,
        title="Manual de Entrega e Ativacao - Menino dos Sonhos",
        author="Sistema de Delivery",
    )
    elementos = []

    elementos += [
        Spacer(1, 1.25 * cm),
        p("Manual de entrega e ativacao", "titulo"),
        p("Sistema de delivery em Python, Flask, SQLite, Mercado Pago, GitHub e Render.", "subtitulo"),
        HRFlowable(width="100%", thickness=2.4, color=VERMELHO, spaceBefore=5, spaceAfter=20),
        p("Este documento explica como entregar o sistema limpo, criar o primeiro administrador, enviar atualizacoes ao GitHub e publicar uma loja no Render.", "texto"),
        aviso("O banco foi preparado para iniciar sem usuarios, produtos, pedidos ou credenciais comerciais. Antes de abrir o painel, crie o primeiro administrador conforme a secao 1."),
        p("Roteiro rapido", "h2"),
        *lista([
            "Criar o primeiro dono (administrador).",
            "Entrar no painel, cadastrar produtos e configurar Mercado Pago, WhatsApp e horario.",
            "Enviar o codigo ao GitHub sem incluir .env, banco de dados ou chaves.",
            "Criar um Web Service no Render com disco persistente e variaveis de ambiente.",
            "Fazer um pedido de teste e confirmar o webhook do Mercado Pago.",
        ]),
        Spacer(1, 16),
        p(f"Documento gerado em {date.today().strftime('%d/%m/%Y')}.", "subtitulo"),
        PageBreak(),
    ]

    elementos += [
        p("1. Criar o primeiro administrador", "h1"),
        p("O arquivo criar_admin.py cria somente o primeiro usuario DONO. Ele nao abre nenhuma pagina publica e se recusa a criar outro dono quando ja existe um, protegendo o painel contra criacao indevida de administradores.", "texto"),
        p("No computador local", "h2"),
        codigo("cd \"C:\\\\caminho\\\\SistemaVenda\"\n.\\.venv\\Scripts\\python.exe criar_admin.py"),
        p("Informe nome completo, nome de usuario e uma senha com pelo menos 12 caracteres. Depois acesse /entrar no endereco do sistema.", "texto"),
        p("No Render", "h2"),
        p("Abra o servico no painel Render, entre em Shell, confirme que esta na pasta do projeto com <b>pwd</b> e execute:", "texto"),
        codigo("python criar_admin.py"),
        aviso("O Shell do Render usa o mesmo banco somente se a variavel DATABASE estiver apontando para o disco persistente, por exemplo /var/data/database.db."),
        p("Usuarios e permissoes", "h2"),
        *lista([
            "DONO: unico administrador. Acessa configuracoes, produtos, usuarios, relatorios e pedidos.",
            "FUNCIONARIO: criado pelo dono em Funcionarios. Acessa pedidos e atualiza o andamento, sem ver credenciais, configuracoes ou relatorios.",
            "Para trocar o dono, faça isso de forma controlada no banco ou entregue um banco limpo e crie o novo primeiro dono. Nao existe cadastro publico de administrador.",
        ]),
        PageBreak(),
    ]

    elementos += [
        p("2. Atualizar e proteger no GitHub", "h1"),
        p("O repositorio recebe apenas codigo. O arquivo .gitignore ja bloqueia .env, bancos .db, backups, chaves e pastas de credenciais.", "texto"),
        p("Primeiro envio ou atualizacao", "h2"),
        codigo("git status\ngit add .\ngit commit -m \"Descreva a alteracao\"\ngit push origin main"),
        p("Se for a primeira configuracao do Git neste computador:", "texto"),
        codigo("git config --global user.name \"SEU_USUARIO\"\ngit config --global user.email \"SEU_EMAIL\""),
        p("Ao executar git push, o GitHub pode abrir o navegador. Entre pela conta Google/Gmail associada ao GitHub e autorize o Git Credential Manager. Nao use senha do GitHub no terminal e nunca cole token de acesso em arquivo, commit, conversa ou tela publica.", "texto"),
        p("Conferencia obrigatoria antes de enviar", "h2"),
        *lista([
            "git status nao pode mostrar .env, database.db, backups ou arquivos de chaves.",
            "Use apenas MERCADOPAGO_ACCESS_TOKEN, SECRET_KEY e demais segredos nas variaveis de ambiente do Render ou na area protegida do painel do dono.",
            "Se uma credencial for enviada por engano ao GitHub, revogue-a no provedor imediatamente; apagar o arquivo depois nao remove o historico.",
        ]),
        PageBreak(),
    ]

    elementos += [
        p("3. Deixar o sistema apto no Render", "h1"),
        p("No Render, crie um novo Web Service conectado ao repositorio do GitHub e selecione a branch main. O Render faz novo deploy a cada push nessa branch.", "texto"),
        p("Configuracao do servico", "h2"),
    ]
    tabela = Table([
        ["Campo", "Valor recomendado"],
        ["Runtime", "Python 3"],
        ["Build Command", "pip install -r requirements-production.txt"],
        ["Start Command", "gunicorn --bind 0.0.0.0:$PORT app:app"],
        ["Health Check Path", "/healthz"],
        ["Branch", "main"],
    ], colWidths=[4.4 * cm, 12.9 * cm])
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), VERMELHO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.6),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#E6E6E6")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    elementos += [
        tabela,
        Spacer(1, 12),
        p("Disco persistente e variaveis", "h2"),
        p("SQLite precisa de um disco persistente. No Render, adicione um disk com ponto de montagem <b>/var/data</b> e crie a variavel <b>DATABASE=/var/data/database.db</b>. Sem disco, o banco e apagado em reinicios ou novos deploys.", "texto"),
        codigo("BASE_URL=https://SEU-SERVICO.onrender.com\nDATABASE=/var/data/database.db\nSESSION_COOKIE_SECURE=true\nSECRET_KEY=uma-chave-aleatoria-longa-e-secreta\nCONFIG_ENCRYPTION_KEY=uma-chave-de-cifragem-secreta"),
        p("Depois do primeiro login do dono, abra Configuracoes e informe o WhatsApp, a URL publica, o token de producao do Mercado Pago e a assinatura secreta do webhook. No Mercado Pago, cadastre a notificacao de pagamentos em:", "texto"),
        codigo("https://SEU-SERVICO.onrender.com/webhook/mercadopago"),
        PageBreak(),
    ]

    elementos += [
        p("4. Mais de um site no Render", "h1"),
        p("Sim. Voce pode criar mais de um Web Service no mesmo usuario Render. Cada Web Service recebe seu proprio endereco onrender.com e pode receber dominio proprio.", "texto"),
        aviso("Este projeto esta no modo de uma loja por publicacao. Para atender negocios diferentes, publique o mesmo repositorio em servicos Render separados, cada um com seu proprio banco, disco, dominio, WhatsApp e credenciais Mercado Pago."),
        p("Modelo para cada nova loja", "h2"),
        *lista([
            "Crie New > Web Service e escolha o mesmo repositorio e branch main.",
            "Escolha um nome exclusivo, por exemplo delivery-loja-b, para receber outro endereco onrender.com.",
            "Adicione um novo disco persistente, tambem em /var/data, exclusivo daquele servico.",
            "Cadastre DATABASE=/var/data/database.db e novas variaveis secretas para essa loja.",
            "Crie o primeiro dono naquele novo servico pelo Shell e configure o Mercado Pago e WhatsApp dele.",
            "Aponte o dominio daquela loja para o novo Web Service, se quiser dominio proprio.",
        ]),
        p("Nao compartilhe um arquivo SQLite, um disco persistente ou o Access Token entre lojas diferentes. Cada uma deve ficar isolada para evitar mistura de pedidos, clientes e recebimentos.", "texto"),
        p("5. Limpar o banco para entrega", "h1"),
        p("O script resetar_banco.py apaga usuarios, produtos, complementos, pedidos, vendas, tentativas de login e configuracoes comerciais. Ele preserva a estrutura e cria uma copia do banco antes da limpeza.", "texto"),
        codigo(".\\.venv\\Scripts\\python.exe resetar_banco.py --confirmar"),
        p("Para limpar o banco que esta no Render, execute o mesmo comando em Shell. Confirme antes se DATABASE aponta para o disco daquele servico. A limpeza local nao apaga automaticamente um banco que esteja no Render.", "texto"),
        p("Checklist final de entrega", "h2"),
        *lista([
            "Banco sem dados comerciais e sem usuario, ou primeiro dono criado pelo novo responsavel.",
            "Nenhuma credencial presente no GitHub, no banco entregue ou em .env.example.",
            "Disco persistente configurado e DATABASE apontando para ele.",
            "BASE_URL usa HTTPS e SESSION_COOKIE_SECURE esta como true em producao.",
            "Pedido de teste aprovado, webhook recebido e status atualizado no painel.",
            "Acesse https://SEU-SERVICO.onrender.com/healthz e confira a resposta status ok.",
        ]),
        Spacer(1, 10),
        p("Referencias: https://render.com/docs/web-services e https://render.com/docs/disks", "rodape"),
    ]

    documento.build(elementos, onFirstPage=cabecalho_rodape, onLaterPages=cabecalho_rodape)
    print(f"Manual criado em: {ARQUIVO_SAIDA}")


if __name__ == "__main__":
    gerar()
