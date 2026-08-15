"""
Management command para importar materiais em massa a partir de uma
planilha Excel no formato da Engemil (aba 'Materiais', com duas tabelas
empilhadas — a segunda, a partir da linha 17, contém os materiais de
verdade; a primeira é de serviços e é ignorada).

Uso:
    python manage.py importar_materiais data/Lista_de_materiais_Engemil.xlsx
"""
import re
from decimal import Decimal

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Material, UnidadeMedida


UNIDADES_PADRAO = {
    'un': 'Unidade',
    'm': 'Metro',
    'm2': 'Metro quadrado',
    'm3': 'Metro cúbico',
    'cm2': 'Centímetro quadrado',
    'cm3': 'Centímetro cúbico',
    'kg': 'Quilograma',
    'pct': 'Pacote',
    'cx': 'Caixa',
}

LINHA_INICIO_MATERIAIS = 18  # primeira linha de dado da Tabela 2 (materiais)


class Command(BaseCommand):
    help = 'Importa materiais em massa a partir da planilha Engemil (.xlsx)'

    def add_arguments(self, parser):
        parser.add_argument('caminho_planilha', type=str)
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula a importação sem gravar nada no banco.',
        )

    def handle(self, *args, **options):
        caminho = options['caminho_planilha']
        dry_run = options['dry_run']

        try:
            wb = openpyxl.load_workbook(caminho, data_only=True)
        except FileNotFoundError:
            raise CommandError(f'Arquivo não encontrado: {caminho}')

        ws = wb['Materiais']

        self.stdout.write('Garantindo que as unidades de medida existem...')
        unidades_por_sigla = self._garantir_unidades(dry_run)

        criados, ignorados, erros = 0, 0, []

        with transaction.atomic():
            for numero_linha, row in enumerate(
                ws.iter_rows(min_row=LINHA_INICIO_MATERIAIS, values_only=True),
                start=LINHA_INICIO_MATERIAIS,
            ):
                _, codigo, descricao, sigla_unidade, _, _, _ = row

                if not codigo or not descricao:
                    continue  # linha vazia ou de fechamento de tabela

                sigla_unidade = (sigla_unidade or '').strip()
                unidade = unidades_por_sigla.get(sigla_unidade)

                if unidade is None:
                    erros.append(
                        f'Linha {numero_linha}: unidade "{sigla_unidade}" '
                        f'desconhecida para o código {codigo}.'
                    )
                    continue

                descricao_limpa = re.sub(r'\s+', ' ', descricao).strip()

                if Material.objects.filter(codigo=codigo).exists():
                    ignorados += 1
                    continue

                if not dry_run:
                    Material.objects.create(
                        codigo=codigo,
                        descricao=descricao_limpa,
                        unidade=unidade,
                        estoque_minimo=Decimal('0'),
                        situacao=Material.Situacao.ATIVO,
                    )
                criados += 1

            if dry_run:
                self.stdout.write(self.style.WARNING(
                    'Modo --dry-run: revertendo a transação, nada foi gravado.'
                ))
                transaction.set_rollback(True)

        self._imprimir_resumo(criados, ignorados, erros, dry_run)

    def _garantir_unidades(self, dry_run: bool) -> dict:
        unidades_por_sigla = {}
        for sigla, descricao in UNIDADES_PADRAO.items():
            if dry_run:
                unidade = UnidadeMedida.objects.filter(sigla=sigla).first()
                if unidade is None:
                    self.stdout.write(f'  (dry-run) criaria unidade: {sigla}')
                    # placeholder só para permitir a simulação prosseguir —
                    # nenhuma unidade real é usada em modo dry-run
                    unidade = True
            else:
                unidade, criada = UnidadeMedida.objects.get_or_create(
                    sigla=sigla, defaults={'descricao': descricao},
                )
                if criada:
                    self.stdout.write(f'  Unidade criada: {sigla} ({descricao})')
            unidades_por_sigla[sigla] = unidade
        return unidades_por_sigla

    def _imprimir_resumo(self, criados, ignorados, erros, dry_run):
        prefixo = '[DRY-RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'\n{prefixo}Materiais {"que seriam criados" if dry_run else "criados"}: {criados}'
        ))
        if ignorados:
            self.stdout.write(self.style.WARNING(
                f'Ignorados (código já existente no banco): {ignorados}'
            ))
        if erros:
            self.stdout.write(self.style.ERROR(f'Erros ({len(erros)}):'))
            for erro in erros[:20]:
                self.stdout.write(f'  - {erro}')
            if len(erros) > 20:
                self.stdout.write(f'  ... e mais {len(erros) - 20} erro(s).')