"""Gera o comprovante em PDF de um pedido do delivery.

O documento e um comprovante operacional do pedido, nao uma NF-e.
"""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def moeda(valor):
    return f"R$ {float(valor or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def texto(valor):
    return escape(str(valor or "-")).replace("\n", "<br/>")


def _cabecalho_rodape(canvas, documento):
    largura, altura = A4
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#312E81"))
    canvas.rect(0, altura - 16 * mm, largura, 16 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(18 * mm, altura - 10 * mm, "COMPROVANTE DO PEDIDO")
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(18 * mm, 11 * mm, "Documento operacional - nao possui valor fiscal")
    canvas.drawRightString(largura - 18 * mm, 11 * mm, f"Pagina {documento.page}")
    canvas.restoreState()


def gerar_comprovante_pedido_pdf(pedido, itens, estabelecimento):
    """Retorna bytes de um PDF pronto para download."""
    arquivo = BytesIO()
    documento = SimpleDocTemplate(
        arquivo,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=26 * mm,
        bottomMargin=20 * mm,
        title=f"Pedido {pedido['id']}",
        author=estabelecimento["nome"] if estabelecimento else "Sistema de Delivery",
    )
    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle(
        "TituloComprovante", parent=estilos["Heading1"], fontName="Helvetica-Bold",
        fontSize=20, leading=24, textColor=colors.HexColor("#172033"), spaceAfter=3 * mm,
    )
    subtitulo = ParagraphStyle(
        "SubtituloComprovante", parent=estilos["BodyText"], fontSize=9, leading=13,
        textColor=colors.HexColor("#64748B"), spaceAfter=6 * mm,
    )
    corpo = ParagraphStyle(
        "CorpoComprovante", parent=estilos["BodyText"], fontSize=9, leading=13,
        textColor=colors.HexColor("#334155"),
    )
    alinhado_direita = ParagraphStyle("Direita", parent=corpo, alignment=TA_RIGHT)
    centralizado = ParagraphStyle("Centro", parent=corpo, alignment=TA_CENTER)
    secoes = []

    nome_loja = estabelecimento["nome"] if estabelecimento else "Sistema de Delivery"
    secoes.append(Paragraph(texto(nome_loja), titulo))
    secoes.append(Paragraph(f"Pedido #{pedido['id']} &middot; criado em {texto(pedido['criado_em'])}", subtitulo))

    informacoes = [
        [Paragraph("<b>Cliente</b><br/>" + texto(pedido["cliente"]), corpo), Paragraph("<b>Telefone</b><br/>" + texto(pedido["telefone"]), corpo)],
        [Paragraph("<b>Endereco de entrega</b><br/>" + texto(pedido["endereco"]), corpo), Paragraph("<b>Pagamento</b><br/>" + texto(pedido["forma_pagamento"]), corpo)],
        [Paragraph("<b>Status do pagamento</b><br/>" + texto(pedido["status_pagamento"]), corpo), Paragraph("<b>Status do pedido</b><br/>" + texto(pedido["status_operacional"]), corpo)],
    ]
    tabela_info = Table(informacoes, colWidths=[87 * mm, 87 * mm], hAlign="LEFT")
    tabela_info.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#E2E8F0")),
        ("INNERGRID", (0, 0), (-1, -1), .5, colors.HexColor("#E2E8F0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    secoes.extend([tabela_info, Spacer(1, 7 * mm)])

    linhas = [[
        Paragraph("<b>Item</b>", corpo),
        Paragraph("<b>Qtd.</b>", centralizado),
        Paragraph("<b>Unitario</b>", alinhado_direita),
        Paragraph("<b>Subtotal</b>", alinhado_direita),
    ]]
    for item in itens:
        subtotal = item["quantidade"] * item["valor_unitario"]
        linhas.append([
            Paragraph(texto(item["descricao"]), corpo),
            Paragraph(str(item["quantidade"]), centralizado),
            Paragraph(moeda(item["valor_unitario"]), alinhado_direita),
            Paragraph(moeda(subtotal), alinhado_direita),
        ])
    tabela_itens = Table(linhas, colWidths=[85 * mm, 20 * mm, 34 * mm, 35 * mm], repeatRows=1, hAlign="LEFT")
    tabela_itens.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2FF")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#312E81")),
        ("LINEBELOW", (0, 0), (-1, -1), .4, colors.HexColor("#E2E8F0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    secoes.extend([tabela_itens, Spacer(1, 6 * mm)])

    resumo = [[Paragraph("Taxa de entrega", corpo), Paragraph(moeda(pedido["valor_entrega"]), alinhado_direita)], [
        Paragraph("<b>Total do pedido</b>", ParagraphStyle("Total", parent=corpo, fontSize=12, textColor=colors.HexColor("#312E81"))),
        Paragraph(f"<b>{moeda(pedido['valor_total'])}</b>", ParagraphStyle("TotalDireita", parent=alinhado_direita, fontSize=12, textColor=colors.HexColor("#312E81"))),
    ]]
    tabela_total = Table(resumo, colWidths=[116 * mm, 58 * mm], hAlign="LEFT")
    tabela_total.setStyle(TableStyle([
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F5F3FF")),
        ("LINEABOVE", (0, 0), (-1, 0), .5, colors.HexColor("#E2E8F0")),
        ("BOX", (0, 1), (-1, 1), .6, colors.HexColor("#C7D2FE")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    secoes.append(tabela_total)
    documento.build(secoes, onFirstPage=_cabecalho_rodape, onLaterPages=_cabecalho_rodape)
    return arquivo.getvalue()
