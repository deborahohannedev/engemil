"""
Popula dados de demonstração ricos, cobrindo os principais fluxos do
sistema (entrada confirmada e pendente, solicitação atendida/parcial/
cancelada, devolução pendente/aprovada/rejeitada, inventário em
andamento e encerrado) — pensado para deixar o ambiente pronto pra
teste manual/demo, não só com o cadastro básico.

Idempotente: cada bloco confere se seu dado-âncora já existe (por
número/nota fiscal) antes de criar, então rodar de novo não duplica.

Pré-requisitos: seed_inicial, seed_teste_perfis e importar_materiais já
devem ter rodado (usa os usuários de teste, o posto/demanda de teste e
os materiais importados).

Uso:
    python manage.py seed_demo
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Fornecedor, Material, Posto, Usuario, Demanda
from devolucoes.domain.services import DevolucaoService
from devolucoes.models import Devolucao
from entradas.domain.services import EntradaService
from entradas.models import Entrada, ItemEntrada
from inventario.domain.services import InventarioService
from inventario.models import Inventario
from solicitacoes.domain.services import SolicitacaoService
from solicitacoes.models import ItemSolicitacao, Solicitacao


class Command(BaseCommand):
    help = 'Popula dados de demonstração ricos (entradas, solicitações, devoluções, inventário).'

    def handle(self, *args, **options):
        self._entrada_service = EntradaService()
        self._solicitacao_service = SolicitacaoService()
        self._devolucao_service = DevolucaoService()
        self._inventario_service = InventarioService()

        try:
            self.almoxarifado = Usuario.objects.get(email='teste.almoxarifado@engemil.com.br')
            self.encarregado1 = Usuario.objects.get(email='teste.encarregado1@engemil.com.br')
            self.encarregado2 = Usuario.objects.get(email='teste.encarregado2@engemil.com.br')
            self.posto = Posto.objects.get(codigo='POSTO-TESTE')
            self.demanda = Demanda.objects.get(numero='DEMANDA-TESTE')
        except (Usuario.DoesNotExist, Posto.DoesNotExist, Demanda.DoesNotExist):
            raise CommandError(
                'Pré-requisitos ausentes — rode antes: '
                'seed_inicial, seed_teste_perfis e importar_materiais.'
            )

        self.stdout.write('Definindo valor unitário em materiais de demonstração...')
        self.materiais = self._definir_precos()

        self.stdout.write('Criando fornecedores de demonstração...')
        self.fornecedor = self._criar_fornecedores()

        self.stdout.write('Criando entradas de demonstração...')
        self._criar_entrada_confirmada()
        self._criar_entrada_pendente()

        self.stdout.write('Criando solicitações de demonstração...')
        self._criar_solicitacao_atendida_com_devolucoes()
        self._criar_solicitacao_parcial()
        self._criar_solicitacao_aberta()
        self._criar_solicitacao_cancelada()

        self.stdout.write('Criando inventários de demonstração...')
        self._criar_inventario_em_andamento()
        self._criar_inventario_encerrado()

        self.stdout.write(self.style.SUCCESS('Seed de demonstração concluído.'))

    # ------------------------------------------------------------------
    # Materiais / fornecedores
    # ------------------------------------------------------------------

    def _definir_precos(self) -> list:
        """
        Só os primeiros N materiais ATIVO ganham valor_unitario — o
        resto fica sem preço de propósito, pra continuar exercitando o
        caminho "material sem preço cadastrado" nas telas. Idempotente:
        se rodado de novo, reaproveita os mesmos materiais já precificados
        em vez de precificar outros 12.
        """
        materiais_com_preco = list(
            Material.objects.filter(situacao=Material.Situacao.ATIVO, valor_unitario__isnull=False)
            .order_by('codigo')[:12]
        )
        faltam = 12 - len(materiais_com_preco)
        if faltam <= 0:
            return materiais_com_preco

        novos = list(
            Material.objects.filter(situacao=Material.Situacao.ATIVO, valor_unitario__isnull=True)
            .order_by('codigo')[:faltam]
        )
        precos = [Decimal('4.50'), Decimal('12.90'), Decimal('89.00'), Decimal('250.00')]
        for i, material in enumerate(novos):
            material.valor_unitario = precos[i % len(precos)]
        Material.objects.bulk_update(novos, ['valor_unitario'])

        return materiais_com_preco + novos

    def _criar_fornecedores(self) -> Fornecedor:
        fornecedor, _ = Fornecedor.objects.get_or_create(
            cnpj='12345678000199',
            defaults={
                'nome': 'Fornecedor Demo Materiais Elétricos Ltda',
                'telefone': '11987654321',
                'email': 'contato@fornecedordemo.com.br',
                'nome_vendedor': 'Carlos Vendedor',
            },
        )
        Fornecedor.objects.get_or_create(
            cnpj='98765432000188',
            defaults={
                'nome': 'Distribuidora Demo Ferragens S.A.',
                'telefone': '11912345678',
                'email': 'vendas@distribuidoradamerican.com.br',
            },
        )
        return fornecedor

    # ------------------------------------------------------------------
    # Entradas
    # ------------------------------------------------------------------

    def _criar_entrada_confirmada(self) -> None:
        if Entrada.objects.filter(nota_fiscal='DEMO-NF-001').exists():
            return

        entrada = Entrada.objects.create(
            fornecedor=self.fornecedor,
            responsavel=self.almoxarifado,
            nota_fiscal='DEMO-NF-001',
            data_entrada=timezone.now(),
        )
        for material in self.materiais[:8]:
            ItemEntrada.objects.create(
                entrada=entrada,
                material=material,
                quantidade=Decimal('50'),
                valor_unitario=material.valor_unitario or Decimal('10.00'),
            )
        self._entrada_service.confirmar(entrada, usuario=self.almoxarifado)

    def _criar_entrada_pendente(self) -> None:
        if Entrada.objects.filter(nota_fiscal='DEMO-NF-002').exists():
            return

        entrada = Entrada.objects.create(
            fornecedor=self.fornecedor,
            responsavel=self.almoxarifado,
            nota_fiscal='DEMO-NF-002',
            data_entrada=timezone.now(),
        )
        for material in self.materiais[8:10]:
            ItemEntrada.objects.create(
                entrada=entrada,
                material=material,
                quantidade=Decimal('20'),
                valor_unitario=material.valor_unitario or Decimal('10.00'),
            )
        # fica sem confirmar de propósito — exercita o caminho "pendente"

    # ------------------------------------------------------------------
    # Solicitações
    # ------------------------------------------------------------------

    def _criar_solicitacao_atendida_com_devolucoes(self) -> None:
        numero = 'DEMO-SOL-001'
        if Solicitacao.objects.filter(numero=numero).exists():
            return

        agora = timezone.now()
        solicitacao = Solicitacao.objects.create(
            numero=numero,
            status=Solicitacao.Status.ABERTA,
            data_solicitacao=agora,
            data_prevista=agora,
            demanda=self.demanda,
            posto=self.posto,
            solicitante=self.encarregado1,
            observacao='Solicitação de demonstração — totalmente atendida, com devoluções.',
        )
        itens = [
            ItemSolicitacao.objects.create(
                solicitacao=solicitacao,
                material=material,
                quantidade_solicitada=Decimal('5'),
                observacao=f'Item de demonstração — {material.codigo}',
            )
            for material in self.materiais[:3]
        ]

        self._solicitacao_service.confirmar_saida(solicitacao, usuario=self.almoxarifado)
        for item in itens:
            item.refresh_from_db()

        # devolução aprovada
        devolucao_aprovada = self._devolucao_service.informar(
            item_solicitacao=itens[0],
            responsavel_conferencia=self.encarregado1,
            quantidade=Decimal('1'),
            condicao=True,
            observacao='Sobrou material — devolução de demonstração (aprovada).',
        )
        self._devolucao_service.aprovar(devolucao_aprovada, usuario=self.almoxarifado)

        # devolução rejeitada (material danificado)
        devolucao_rejeitada = self._devolucao_service.informar(
            item_solicitacao=itens[1],
            responsavel_conferencia=self.encarregado1,
            quantidade=Decimal('1'),
            condicao=False,
            observacao='Material voltou danificado — devolução de demonstração (rejeitada).',
        )
        self._devolucao_service.rejeitar(
            devolucao_rejeitada, usuario=self.almoxarifado, motivo='Material sem condição de uso.',
        )

        # devolução pendente, aguardando conferência
        self._devolucao_service.informar(
            item_solicitacao=itens[2],
            responsavel_conferencia=self.encarregado1,
            quantidade=Decimal('1'),
            condicao=True,
            observacao='Devolução de demonstração ainda pendente de decisão.',
        )

    def _criar_solicitacao_parcial(self) -> None:
        numero = 'DEMO-SOL-002'
        if Solicitacao.objects.filter(numero=numero).exists():
            return

        material_disponivel = self.materiais[3]
        material_indisponivel, _ = Material.objects.get_or_create(
            codigo='DEMO-MAT-SEM-ESTOQUE',
            defaults={
                'descricao': 'Material de demonstração sem estoque',
                'unidade': material_disponivel.unidade,
                'situacao': Material.Situacao.ATIVO,
            },
        )

        agora = timezone.now()
        solicitacao = Solicitacao.objects.create(
            numero=numero,
            status=Solicitacao.Status.ABERTA,
            data_solicitacao=agora,
            data_prevista=agora,
            demanda=self.demanda,
            posto=self.posto,
            solicitante=self.encarregado2,
            observacao='Solicitação de demonstração — parcialmente atendida (um item sem estoque).',
        )
        ItemSolicitacao.objects.create(
            solicitacao=solicitacao,
            material=material_disponivel,
            quantidade_solicitada=Decimal('2'),
            observacao='Item com estoque disponível.',
        )
        ItemSolicitacao.objects.create(
            solicitacao=solicitacao,
            material=material_indisponivel,
            quantidade_solicitada=Decimal('2'),
            observacao='Item propositalmente sem estoque — fica INDISPONIVEL.',
        )

        self._solicitacao_service.confirmar_saida(solicitacao, usuario=self.almoxarifado)

    def _criar_solicitacao_aberta(self) -> None:
        numero = 'DEMO-SOL-003'
        if Solicitacao.objects.filter(numero=numero).exists():
            return

        agora = timezone.now()
        solicitacao = Solicitacao.objects.create(
            numero=numero,
            status=Solicitacao.Status.ABERTA,
            data_solicitacao=agora,
            data_prevista=agora,
            demanda=self.demanda,
            posto=self.posto,
            solicitante=self.encarregado1,
            observacao='Solicitação de demonstração — ainda aberta, aguardando confirmação de saída.',
        )
        ItemSolicitacao.objects.create(
            solicitacao=solicitacao,
            material=self.materiais[4],
            quantidade_solicitada=Decimal('3'),
            observacao='Item de demonstração aguardando saída.',
        )

    def _criar_solicitacao_cancelada(self) -> None:
        numero = 'DEMO-SOL-004'
        if Solicitacao.objects.filter(numero=numero).exists():
            return

        agora = timezone.now()
        solicitacao = Solicitacao.objects.create(
            numero=numero,
            status=Solicitacao.Status.ABERTA,
            data_solicitacao=agora,
            data_prevista=agora,
            demanda=self.demanda,
            posto=self.posto,
            solicitante=self.encarregado2,
            observacao='Solicitação de demonstração — cancelada.',
        )
        ItemSolicitacao.objects.create(
            solicitacao=solicitacao,
            material=self.materiais[5],
            quantidade_solicitada=Decimal('1'),
            observacao='Item de uma solicitação que foi cancelada.',
        )
        self._solicitacao_service.cancelar(solicitacao)

    # ------------------------------------------------------------------
    # Inventário
    # ------------------------------------------------------------------

    def _criar_inventario_em_andamento(self) -> None:
        observacao = 'Inventário de demonstração — em andamento.'
        if Inventario.objects.filter(observacao=observacao).exists():
            return

        # iniciar() sempre inclui todos os materiais ATIVO agora (pedido do
        # cliente) — não seleciona mais um subconjunto.
        inventario = self._inventario_service.iniciar(observacao=observacao)
        # conta só uma parte dos itens de propósito — fica EM_ANDAMENTO
        for item in inventario.itens.all()[:2]:
            self._inventario_service.registrar_contagem_fisica(item, item.quantidade_sistema)

    def _criar_inventario_encerrado(self) -> None:
        observacao = 'Inventário de demonstração — encerrado, com divergência.'
        if Inventario.objects.filter(observacao=observacao).exists():
            return

        inventario = self._inventario_service.iniciar(observacao=observacao)
        itens = list(inventario.itens.all())
        for i, item in enumerate(itens):
            # o primeiro item conta com divergência de propósito, pra
            # exercitar o ajuste automático de estoque no encerramento
            divergencia = Decimal('1') if i == 0 else Decimal('0')
            self._inventario_service.registrar_contagem_fisica(
                item, item.quantidade_sistema + divergencia,
            )

        self._inventario_service.encerrar(inventario, usuario=self.almoxarifado)
