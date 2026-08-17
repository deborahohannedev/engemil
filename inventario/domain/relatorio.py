"""
Geração do laudo (PDF) de um Inventário — RF pedido pela Deborah: um
documento com o resultado completo da contagem, pra apresentar/arquivar.
Usa reportlab (sem dependência de sistema, diferente de weasyprint/wkhtmltopdf
— importante pro deploy no Render sem Docker).
"""
import io

from django.conf import settings
from django.db.models import Prefetch
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from core.models import Movimentacao
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
    # destaque pro caso de erro (InventarioService.encerrar): item com
    # divergência calculada mas SEM ajuste aplicado — precisa de resolução
    # manual. Sem isso a observação de erro fica visualmente igual a uma
    # observação qualquer, fácil de passar batido numa tabela grande.
    estilo_celula_erro = ParagraphStyle(
        'celula_erro', parent=estilo_celula, textColor=colors.HexColor('#a8071a'),
    )
    elementos = []

    if LOGO_PATH.exists():
        elementos.append(Image(str(LOGO_PATH), width=5 * cm, height=2.1 * cm))
        elementos.append(Spacer(1, 0.4 * cm))

    elementos.append(Paragraph('Laudo de Inventário', styles['Title']))
    elementos.append(Spacer(1, 0.3 * cm))

    # 'movimentacoes_ajuste' traz a Movimentacao real gerada pelo ajuste
    # deste item (se algum foi aplicado) — dá pra mostrar no laudo o
    # reajuste que de fato aconteceu no sistema (quantidade real antes/
    # depois), não só a divergência calculada contra o retrato do início
    # do inventário (que pode ter ficado desatualizado nesse meio-tempo —
    # ver InventarioService.encerrar()).
    itens = list(
        inventario.itens.select_related('material', 'material__unidade')
        .prefetch_related(Prefetch(
            'movimentacoes',
            queryset=Movimentacao.objects.filter(tipo=Movimentacao.Tipo.AJUSTE_INVENTARIO),
            to_attr='movimentacoes_ajuste',
        ))
        .all()
    )
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
        'Divergência', 'Ajuste', 'Estoque Real\nAntes → Depois', 'Observação',
    ]
    linhas = [cabecalho_itens]
    linhas_com_pendencia = []
    for item in itens:
        # mesmo caso tratado em InventarioService.encerrar(): divergência
        # calculada mas ajuste não pôde ser aplicado (saldo atual do
        # material não comportava) — fica marcado pra resolução manual.
        tem_pendencia = item.ajuste is None and item.divergencia is not None and item.divergencia != 0
        if tem_pendencia:
            linhas_com_pendencia.append(len(linhas))  # índice desta linha na tabela

        # quantidade_anterior/posterior são os valores REAIS do estoque no
        # momento em que o ajuste foi de fato aplicado — podem diferir de
        # quantidade_sistema/quantidade_fisica se outra movimentação mexeu
        # no material entre o início do inventário e o encerramento.
        movs_ajuste = item.movimentacoes_ajuste
        reajuste_sistema = (
            f'{_fmt_quantidade(movs_ajuste[0].quantidade_anterior)} → '
            f'{_fmt_quantidade(movs_ajuste[0].quantidade_posterior)}'
        ) if movs_ajuste else '—'

        estilo_observacao = estilo_celula_erro if tem_pendencia else estilo_celula
        linhas.append([
            Paragraph(item.material.codigo, estilo_celula),
            Paragraph(item.material.descricao, estilo_celula),
            item.material.unidade.sigla,
            _fmt_quantidade(item.quantidade_sistema),
            _fmt_quantidade(item.quantidade_fisica),
            _fmt_quantidade(item.divergencia),
            _fmt_quantidade(item.ajuste),
            reajuste_sistema,
            Paragraph(item.observacao or '—', estilo_observacao),
        ])

    tabela_itens = Table(
        linhas,
        colWidths=[2.2 * cm, 5.8 * cm, 1.6 * cm, 2.2 * cm, 2.2 * cm, 2.2 * cm, 2 * cm, 2.8 * cm, None],
        repeatRows=1,
    )
    estilo_tabela = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2b2b2b')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d9d9d9')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
    ]
    # linha inteira em vermelho claro pra item com pendência — sobrepõe o
    # zebra-striping do ROWBACKGROUNDS acima (regras posteriores da
    # TableStyle vencem as anteriores pra célula em comum).
    for linha_idx in linhas_com_pendencia:
        estilo_tabela.append(
            ('BACKGROUND', (0, linha_idx), (-1, linha_idx), colors.HexColor('#fff1f0')),
        )
    tabela_itens.setStyle(TableStyle(estilo_tabela))
    elementos.append(tabela_itens)

    if linhas_com_pendencia:
        plural = len(linhas_com_pendencia) != 1
        elementos.append(Spacer(1, 0.3 * cm))
        elementos.append(Paragraph(
            f'⚠ {len(linhas_com_pendencia)} '
            f'{"itens destacados" if plural else "item destacado"} em vermelho '
            f'{"ficaram" if plural else "ficou"} com ajuste pendente de resolução manual — '
            f'ver observação de cada um.',
            ParagraphStyle('aviso', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#a8071a')),
        ))

    doc.build(elementos)
    return buffer.getvalue()
