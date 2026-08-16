"""
Geração do laudo (PDF) de um Inventário — RF pedido pela Deborah: um
documento com o resultado completo da contagem, pra apresentar/arquivar.
Usa reportlab (sem dependência de sistema, diferente de weasyprint/wkhtmltopdf
— importante pro deploy no Render sem Docker).
"""
import io

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from inventario.models import Inventario

LOGO_PATH = settings.BASE_DIR / 'data' / 'logo.jpeg'


def _fmt_data(valor):
    return valor.strftime('%d/%m/%Y %H:%M') if valor else '—'


def _fmt_quantidade(valor):
    if valor is None:
        return '—'
    texto = f'{valor:.3f}'.rstrip('0').rstrip('.')
    return texto if texto else '0'


def gerar_laudo_pdf(inventario: Inventario) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
    )
    styles = getSampleStyleSheet()
    # colunas de texto (código/descrição/observação) usam Paragraph — uma
    # string simples não quebra linha na Table do reportlab, ela atropela
    # a célula vizinha quando é mais larga que a coluna (bug real visto no
    # teste manual com um código de material longo)
    estilo_celula = ParagraphStyle('celula', parent=styles['Normal'], fontSize=8, leading=10)
    estilo_celula_cabecalho = ParagraphStyle('celula_cabecalho', parent=styles['Normal'], fontSize=9, leading=11)
    elementos = []

    if LOGO_PATH.exists():
        elementos.append(Image(str(LOGO_PATH), width=5 * cm, height=2.1 * cm))
        elementos.append(Spacer(1, 0.4 * cm))

    elementos.append(Paragraph('Laudo de Inventário', styles['Title']))
    elementos.append(Spacer(1, 0.3 * cm))

    itens = list(inventario.itens.select_related('material', 'material__unidade').all())
    contados = sum(1 for item in itens if item.foi_contado())

    def _p(texto):
        return Paragraph(texto, estilo_celula_cabecalho)

    dados_cabecalho = [
        ['Data Início', _fmt_data(inventario.data_inicio), 'Situação', _p(inventario.get_situacao_display())],
        [
            'Encerrado Em', _fmt_data(inventario.encerrado_em),
            'Encerrado Por', _p(str(inventario.encerrado_por) if inventario.encerrado_por else '—'),
        ],
        ['Itens Contados', f'{contados} / {len(itens)}', 'Observação', _p(inventario.observacao or '—')],
    ]
    tabela_cabecalho = Table(dados_cabecalho, colWidths=[3 * cm, 6 * cm, 3 * cm, None])
    tabela_cabecalho.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d9d9d9')),
    ]))
    elementos.append(tabela_cabecalho)
    elementos.append(Spacer(1, 0.5 * cm))

    cabecalho_itens = [
        'Código', 'Descrição', 'Unidade', 'Qtd. Sistema', 'Qtd. Física',
        'Divergência', 'Ajuste', 'Observação',
    ]
    linhas = [cabecalho_itens]
    for item in itens:
        linhas.append([
            Paragraph(item.material.codigo, estilo_celula),
            Paragraph(item.material.descricao, estilo_celula),
            item.material.unidade.sigla,
            _fmt_quantidade(item.quantidade_sistema),
            _fmt_quantidade(item.quantidade_fisica),
            _fmt_quantidade(item.divergencia),
            _fmt_quantidade(item.ajuste),
            Paragraph(item.observacao or '—', estilo_celula),
        ])

    tabela_itens = Table(
        linhas,
        colWidths=[2.3 * cm, 7 * cm, 1.8 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 2.2 * cm, None],
        repeatRows=1,
    )
    tabela_itens.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2b2b2b')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d9d9d9')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
    ]))
    elementos.append(tabela_itens)

    doc.build(elementos)
    return buffer.getvalue()
