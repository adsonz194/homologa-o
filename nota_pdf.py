"""Gera um cupom operacional de pedido para impressao ou compartilhamento.

O arquivo nao e NF-e, NFC-e nem documento fiscal. Ele registra os dados
operacionais que a loja e o cliente precisam para preparar e entregar o pedido.
"""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


LARGURA_CUPOM = 80 * mm
MARGEM = 5 * mm
COR_PAPEL = colors.HexColor("#FFFDD1")
COR_LINHA = colors.HexColor("#303028")


def moeda(valor):
    return f"R$ {float(valor or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def texto(valor):
    return escape(str(valor or "-")).replace("\n", "<br/>")


def _altura_cupom(itens):
    linhas_itens = sum(max(1, (len(str(item["descricao"] or "")) + 29) // 30) for item in itens)
    # A altura cresce de acordo com a descricao dos itens, evitando que o
    # rodape do cupom seja cortado quando houver complementos.
    return max(182 * mm, (148 + 9 * len(itens) + 3.8 * linhas_itens) * mm)


def _fundo_cupom(canvas, documento):
    canvas.saveState()
    largura, altura = documento.pagesize
    canvas.setFillColor(COR_PAPEL)
    canvas.rect(0, 0, largura, altura, fill=1, stroke=0)
    canvas.restoreState()


def _linha_horizontal():
    tabela = Table([["" ]], colWidths=[70 * mm], rowHeights=[0.35 * mm])
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COR_LINHA),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tabela


def gerar_comprovante_pedido_pdf(pedido, itens, estabelecimento):
    """Retorna bytes de um comprovante no formato estreito de cupom."""
    arquivo = BytesIO()
    documento = SimpleDocTemplate(
        arquivo,
        pagesize=(LARGURA_CUPOM, _altura_cupom(itens)),
        leftMargin=MARGEM,
        rightMargin=MARGEM,
        topMargin=5 * mm,
        bottomMargin=5 * mm,
        title=f"Comprovante do pedido {pedido['id']}",
        author=estabelecimento["nome"] if estabelecimento else "Delivery",
    )
    estilos = getSampleStyleSheet()
    cabecalho = ParagraphStyle(
        "CupomCabecalho", parent=estilos["BodyText"], fontName="Helvetica-Bold",
        fontSize=10, leading=12, alignment=TA_CENTER, textColor=colors.black,
    )
    centralizado = ParagraphStyle(
        "CupomCentro", parent=estilos["BodyText"], fontSize=6.7, leading=8.3,
        alignment=TA_CENTER, textColor=colors.black,
    )
    normal = ParagraphStyle(
        "CupomNormal", parent=estilos["BodyText"], fontSize=7, leading=8.4,
        textColor=colors.black,
    )
    pequeno = ParagraphStyle(
        "CupomPequeno", parent=normal, fontSize=6, leading=7.2,
    )
    direita = ParagraphStyle("CupomDireita", parent=normal, alignment=TA_RIGHT)
    direita_pequeno = ParagraphStyle("CupomDireitaPequeno", parent=pequeno, alignment=TA_RIGHT)
    centro_pequeno = ParagraphStyle("CupomCentroPequeno", parent=pequeno, alignment=TA_CENTER)
    secoes = []

    loja = estabelecimento or {}
    nome_fantasia = loja["nome"] if loja else "Delivery"
    razao_social = loja["razao_social"] if loja and loja["razao_social"] else nome_fantasia
    secoes.append(Paragraph(texto(nome_fantasia).upper(), cabecalho))
    secoes.append(Paragraph(texto(razao_social).upper(), centralizado))
    if loja and loja["endereco"]:
        secoes.append(Paragraph(texto(loja["endereco"]), centralizado))
    contatos = []
    if loja and loja["telefone"]:
        contatos.append(f"Tel.: {texto(loja['telefone'])}")
    if loja and loja["whatsapp"]:
        contatos.append(f"WhatsApp: {texto(loja['whatsapp'])}")
    if contatos:
        secoes.append(Paragraph(" · ".join(contatos), centralizado))
    if loja and loja["cnpj"]:
        secoes.append(Paragraph(f"CNPJ: {texto(loja['cnpj'])}", centralizado))
    secoes.extend([Spacer(1, 1.6 * mm), _linha_horizontal(), Spacer(1, 1.7 * mm)])

    numero = f"{int(pedido['id']):06d}"
    bloco_pedido = [
        [Paragraph("<b>COMPROVANTE DO PEDIDO</b>", normal), Paragraph(f"<b>No {numero}</b>", direita)],
        [Paragraph(f"Data: {texto(pedido['criado_em'])}", pequeno), Paragraph("VENDA ONLINE", direita_pequeno)],
    ]
    tabela_pedido = Table(bloco_pedido, colWidths=[45 * mm, 25 * mm])
    tabela_pedido.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2 * mm),
    ]))
    secoes.extend([tabela_pedido, _linha_horizontal(), Spacer(1, 1.7 * mm)])
    secoes.append(Paragraph(f"<b>CLIENTE:</b> {texto(pedido['cliente'])}", normal))
    secoes.append(Paragraph(f"<b>TELEFONE:</b> {texto(pedido['telefone'])}", normal))
    recebimento = "RETIRADA NA LOJA" if pedido["modalidade_entrega"] == "RETIRADA" else f"ENTREGA - {texto(pedido['local_entrega'])}<br/>{texto(pedido['endereco'])}"
    secoes.append(Paragraph(f"<b>RECEBIMENTO:</b> {recebimento}", normal))
    if pedido["agendado_para"]:
        secoes.append(Paragraph(f"<b>AGENDADO PARA:</b> {texto(pedido['agendado_para'])}", normal))
    elif pedido["prazo_entrega_minutos"]:
        secoes.append(Paragraph(f"<b>PREVISAO DE ENTREGA:</b> cerca de {texto(pedido['prazo_entrega_minutos'])} minutos", normal))
    if pedido["observacao"]:
        secoes.append(Paragraph(f"<b>OBSERVACAO:</b> {texto(pedido['observacao'])}", normal))
    secoes.extend([Spacer(1, 1.6 * mm), _linha_horizontal(), Spacer(1, 1.4 * mm)])

    linhas = [[
        Paragraph("<b>COD.</b>", pequeno), Paragraph("<b>DESCRICAO</b>", pequeno),
        Paragraph("<b>QTD x UN.</b>", centro_pequeno), Paragraph("<b>VALOR</b>", direita_pequeno),
    ]]
    for item in itens:
        codigo_item = item["codigo_interno"] if "codigo_interno" in item.keys() and item["codigo_interno"] else str(item["produto_id"])
        subtotal = item["quantidade"] * item["valor_unitario"]
        linhas.append([
            Paragraph(texto(codigo_item), pequeno),
            Paragraph(texto(item["descricao"]), pequeno),
            Paragraph(f"{item['quantidade']} x<br/>{moeda(item['valor_unitario'])}", centro_pequeno),
            Paragraph(moeda(subtotal), direita_pequeno),
        ])
    tabela_itens = Table(linhas, colWidths=[10 * mm, 31 * mm, 13 * mm, 16 * mm], repeatRows=1)
    tabela_itens.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, COR_LINHA),
        ("LINEBELOW", (0, 1), (-1, -1), 0.18, colors.HexColor("#777766")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0.5 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 0.5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.0 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.0 * mm),
    ]))
    secoes.extend([tabela_itens, Spacer(1, 2 * mm), _linha_horizontal(), Spacer(1, 1.4 * mm)])

    totais = [[Paragraph("<b>Total do pedido</b>", normal), Paragraph(f"<b>{moeda(pedido['valor_total'])}</b>", direita)]]
    if float(pedido["valor_entrega"] or 0) > 0:
        totais.insert(0, [Paragraph("Taxa de entrega", normal), Paragraph(moeda(pedido["valor_entrega"]), direita)])
    if pedido["forma_pagamento"] == "DINHEIRO":
        totais.extend([
            [Paragraph("Valor informado para pagamento", normal), Paragraph(moeda(pedido["valor_recebido"]), direita)],
            [Paragraph("Troco a levar", normal), Paragraph(moeda(pedido["troco"]), direita)],
        ])
    tabela_totais = Table(totais, colWidths=[47 * mm, 23 * mm])
    tabela_totais.setStyle(TableStyle([
        ("LINEABOVE", (0, -1), (-1, -1), 0.45, COR_LINHA),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0.8 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8 * mm),
    ]))
    secoes.extend([tabela_totais, Spacer(1, 1.4 * mm), _linha_horizontal(), Spacer(1, 1.6 * mm)])

    secoes.append(Paragraph(f"<b>FORMA DE PAGAMENTO:</b> {texto(pedido['forma_pagamento'])}", normal))
    secoes.append(Paragraph(f"<b>STATUS DO PAGAMENTO:</b> {texto(pedido['status_pagamento'])}", normal))
    secoes.append(Paragraph(f"<b>STATUS DO PEDIDO:</b> {texto(pedido['status_operacional'])}", normal))
    if pedido["modalidade_entrega"] == "ENTREGA" and pedido["codigo_entrega"]:
        secoes.extend([Spacer(1, 1.8 * mm), Paragraph(f"<b>CODIGO DE ENTREGA: {texto(pedido['codigo_entrega'])}</b>", centralizado), Paragraph("Informe este codigo somente ao entregador na entrega.", centro_pequeno)])
    secoes.extend([
        Spacer(1, 3 * mm), _linha_horizontal(), Spacer(1, 4 * mm),
        Paragraph("ASSINATURA DO CLIENTE", centralizado), Spacer(1, 3 * mm), _linha_horizontal(), Spacer(1, 2 * mm),
        Paragraph("DOCUMENTO OPERACIONAL - NAO POSSUI VALOR FISCAL", centralizado),
        Paragraph("Obrigado e volte sempre!", centralizado),
    ])
    documento.build(secoes, onFirstPage=_fundo_cupom, onLaterPages=_fundo_cupom)
    return arquivo.getvalue()
