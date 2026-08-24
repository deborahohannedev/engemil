from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Material, Movimentacao, Perfil, Posto, UnidadeMedida, Usuario
from solicitacoes.domain.services import (
    DisponibilidadeInsuficienteError, DisponivelParaRetiradaInvalidaError,
    QuantidadeSaidaSenadoInvalidaError, ResponsavelRetiradaObrigatorioError,
    SeparacaoInvalidaError, SolicitacaoService,
)
from solicitacoes.models import ItemSolicitacao, Solicitacao


class ConfirmarSaidaSenadoTests(TestCase):
    """
    Cobre a acumulação/validação de ItemSolicitacao.quantidade_saida_senado
    no fluxo de confirmar_saida. quantidade_atendida sempre reflete o total
    entregue; só (quantidade_atendida - quantidade_saida_senado) é de fato
    debitado do Material.estoque_real — a fração Senado não sai do estoque
    controlado pela aplicação.

    confirmar_saida só opera sobre itens já SEPARADO (ver SeparacaoTests) —
    por isso todo teste aqui separa o item por inteiro antes de confirmar.
    """

    def setUp(self):
        perfil = Perfil.objects.create(nome='Almoxarifado', funcao='ALMOXARIFADO')
        self.usuario = Usuario.objects.create_user(
            cpf='52998224725', nome='Teste', sobrenome='Almoxarifado',
            email='almoxarifado@teste.com', perfil=perfil,
        )
        self.posto = Posto.objects.create(codigo='POSTO-1', nome='Posto 1')
        unidade = UnidadeMedida.objects.create(sigla='UN', descricao='Unidade')
        self.material = Material.objects.create(
            codigo='MAT-1', descricao='Material teste', unidade=unidade,
            estoque_real=Decimal('100'),
        )
        self.solicitacao = Solicitacao.objects.create(
            numero='SOL-1', posto=self.posto, solicitante=self.usuario,
            data_solicitacao=timezone.now(),
        )
        self.item = ItemSolicitacao.objects.create(
            solicitacao=self.solicitacao, material=self.material,
            quantidade_solicitada=Decimal('10'),
        )
        self.service = SolicitacaoService()

    def test_confirmar_saida_acumula_quantidade_senado(self):
        # 10 pendentes, 4 vieram do Senado — só 6 saem do Material (100 - 6 = 94)
        self.service.separar(self.item, Decimal('10'))
        self.service.confirmar_saida(
            self.solicitacao, usuario=self.usuario, responsavel_retirada='João Retirada',
            quantidades_senado={self.item.id: Decimal('4')},
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade_atendida, Decimal('10'))
        self.assertEqual(self.item.quantidade_saida_senado, Decimal('4'))
        self.material.refresh_from_db()
        self.assertEqual(self.material.estoque_real, Decimal('94'))

    def test_confirmar_saida_sem_quantidade_senado_debita_tudo_do_material(self):
        self.service.separar(self.item, Decimal('10'))
        self.service.confirmar_saida(
            self.solicitacao, usuario=self.usuario, responsavel_retirada='João Retirada',
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade_saida_senado, Decimal('0'))
        self.material.refresh_from_db()
        self.assertEqual(self.material.estoque_real, Decimal('90'))

    def test_exemplo_do_cliente_estoque_10_atendida_2_senado_1(self):
        # estoque_real=10, quantidade_atendida=2, quantidade_senado=1 —
        # só 1 unidade é debitada do Material (10 - 1 = 9).
        self.item.quantidade_solicitada = Decimal('2')
        self.item.save(update_fields=['quantidade_solicitada'])
        self.material.estoque_real = Decimal('10')
        self.material.save(update_fields=['estoque_real'])

        self.service.separar(self.item, Decimal('2'))
        self.service.confirmar_saida(
            self.solicitacao, usuario=self.usuario, responsavel_retirada='João Retirada',
            quantidades_senado={self.item.id: Decimal('1')},
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade_atendida, Decimal('2'))
        self.assertEqual(self.item.quantidade_saida_senado, Decimal('1'))
        self.material.refresh_from_db()
        self.assertEqual(self.material.estoque_real, Decimal('9'))

    def test_saida_totalmente_coberta_pelo_senado_nao_debita_material(self):
        self.service.separar(self.item, Decimal('10'))
        self.service.confirmar_saida(
            self.solicitacao, usuario=self.usuario, responsavel_retirada='João Retirada',
            quantidades_senado={self.item.id: Decimal('10')},
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade_atendida, Decimal('10'))
        self.assertEqual(self.item.quantidade_saida_senado, Decimal('10'))
        self.assertEqual(self.item.status, ItemSolicitacao.Status.ATENDIDO)
        self.material.refresh_from_db()
        self.assertEqual(self.material.estoque_real, Decimal('100'))

    def test_disponibilidade_considera_fracao_senado(self):
        # separa os 10 com estoque de sobra, mas o estoque caiu pra 3 até a
        # hora de confirmar (consumido por outra solicitação nesse meio-
        # tempo) — 8 das 10 vêm do Senado agora, então só 2 precisam
        # existir no estoque próprio nesse momento pra confirmar normal.
        self.service.separar(self.item, Decimal('10'))
        self.material.estoque_real = Decimal('3')
        self.material.save(update_fields=['estoque_real'])

        self.service.confirmar_saida(
            self.solicitacao, usuario=self.usuario, responsavel_retirada='João Retirada',
            quantidades_senado={self.item.id: Decimal('8')},
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemSolicitacao.Status.ATENDIDO)
        self.assertEqual(self.item.quantidade_atendida, Decimal('10'))
        self.material.refresh_from_db()
        self.assertEqual(self.material.estoque_real, Decimal('1'))

    def test_confirmacoes_parciais_somam_quantidade_senado(self):
        # confirmar_saida move o saldo_pendente do item inteiro (não aceita
        # quantidade parcial por chamada) — pra simular duas confirmações
        # reais, primeiro separa+atende os 6 solicitados, depois aumenta a
        # quantidade_solicitada (mesma mecânica de SolicitacaoEditSerializer,
        # que reabre o item pra PENDENTE) e separa+confirma o restante.
        self.item.quantidade_solicitada = Decimal('6')
        self.item.save(update_fields=['quantidade_solicitada'])
        self.material.estoque_real = Decimal('6')
        self.material.save(update_fields=['estoque_real'])

        self.service.separar(self.item, Decimal('6'))
        self.service.confirmar_saida(
            self.solicitacao, usuario=self.usuario, responsavel_retirada='João Retirada',
            quantidades_senado={self.item.id: Decimal('2')},
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade_atendida, Decimal('6'))
        self.assertEqual(self.item.quantidade_saida_senado, Decimal('2'))
        self.assertEqual(self.item.status, ItemSolicitacao.Status.ATENDIDO)
        self.material.refresh_from_db()
        self.assertEqual(self.material.estoque_real, Decimal('2'))  # 6 - (6-2)

        # pede mais 4 (reabre o item pra PENDENTE, igual SolicitacaoEditSerializer
        # faria) e repõe estoque pra separar + confirmar o restante
        self.item.quantidade_solicitada = Decimal('10')
        self.item.status = ItemSolicitacao.Status.PENDENTE
        self.item.save(update_fields=['quantidade_solicitada', 'status'])
        # SolicitacaoEditSerializer.update() também chama isso — sem, a
        # solicitação ficaria travada em ATENDIDA (fixada na 1ª confirmação)
        # e separar() rejeitaria por status inválido.
        self.service.reconciliar_status_apos_edicao(self.solicitacao)
        self.material.estoque_real = Decimal('4')
        self.material.save(update_fields=['estoque_real'])

        self.service.separar(self.item, Decimal('4'))  # falta_separar = 10 - 6
        self.service.confirmar_saida(
            self.solicitacao, usuario=self.usuario, responsavel_retirada='João Retirada',
            quantidades_senado={self.item.id: Decimal('1')},
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade_atendida, Decimal('10'))
        self.assertEqual(self.item.quantidade_saida_senado, Decimal('3'))
        self.material.refresh_from_db()
        self.assertEqual(self.material.estoque_real, Decimal('1'))  # 4 - (4-1)

    def test_quantidade_senado_maior_que_movimentada_levanta_erro(self):
        self.service.separar(self.item, Decimal('10'))
        with self.assertRaises(QuantidadeSaidaSenadoInvalidaError):
            self.service.confirmar_saida(
                self.solicitacao, usuario=self.usuario, responsavel_retirada='João Retirada',
                quantidades_senado={self.item.id: Decimal('11')},
            )
        self.item.refresh_from_db()
        self.material.refresh_from_db()
        # nada deve ter sido gravado — transação revertida
        self.assertEqual(self.item.quantidade_atendida, Decimal('0'))
        self.assertEqual(self.material.estoque_real, Decimal('100'))

    def test_quantidade_senado_para_item_fora_do_lote_levanta_erro(self):
        import uuid

        self.service.separar(self.item, Decimal('10'))
        with self.assertRaises(QuantidadeSaidaSenadoInvalidaError):
            self.service.confirmar_saida(
                self.solicitacao, usuario=self.usuario, responsavel_retirada='João Retirada',
                quantidades_senado={uuid.uuid4(): Decimal('1')},
            )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade_atendida, Decimal('0'))


class ResponsavelRetiradaTests(TestCase):
    """
    Cobre a obrigatoriedade de responsavel_retirada em confirmar_saida e a
    gravação em Movimentacao.responsavel_retirada.
    """

    def setUp(self):
        perfil = Perfil.objects.create(nome='Almoxarifado', funcao='ALMOXARIFADO')
        self.usuario = Usuario.objects.create_user(
            cpf='52998224725', nome='Teste', sobrenome='Almoxarifado',
            email='almoxarifado-resp@teste.com', perfil=perfil,
        )
        self.posto = Posto.objects.create(codigo='POSTO-RESP', nome='Posto Responsável')
        unidade = UnidadeMedida.objects.create(sigla='UN-RESP', descricao='Unidade Resp')
        self.material = Material.objects.create(
            codigo='MAT-RESP', descricao='Material responsável', unidade=unidade,
            estoque_real=Decimal('20'),
        )
        self.solicitacao = Solicitacao.objects.create(
            numero='SOL-RESP-1', posto=self.posto, solicitante=self.usuario,
            data_solicitacao=timezone.now(),
        )
        self.item = ItemSolicitacao.objects.create(
            solicitacao=self.solicitacao, material=self.material,
            quantidade_solicitada=Decimal('10'),
        )
        self.service = SolicitacaoService()
        self.service.separar(self.item, Decimal('10'))

    def test_confirmar_saida_sem_responsavel_retirada_levanta_erro(self):
        with self.assertRaises(ResponsavelRetiradaObrigatorioError):
            self.service.confirmar_saida(self.solicitacao, usuario=self.usuario)

    def test_confirmar_saida_com_responsavel_retirada_em_branco_levanta_erro(self):
        with self.assertRaises(ResponsavelRetiradaObrigatorioError):
            self.service.confirmar_saida(
                self.solicitacao, usuario=self.usuario, responsavel_retirada='   ',
            )

    def test_confirmar_saida_grava_responsavel_retirada_na_movimentacao(self):
        self.service.confirmar_saida(
            self.solicitacao, usuario=self.usuario, responsavel_retirada='  Maria Retirada  ',
        )
        movimentacao = Movimentacao.objects.get(material=self.material)
        self.assertEqual(movimentacao.responsavel_retirada, 'Maria Retirada')

    def test_view_confirmar_saida_sem_responsavel_retirada_retorna_400(self):
        client = APIClient()
        client.force_authenticate(self.usuario)
        response = client.post(f'/api/solicitacoes/{self.solicitacao.id}/confirmar-saida/', {}, format='json')
        self.assertEqual(response.status_code, 400)


class SeparacaoTests(TestCase):
    """
    Cobre SolicitacaoService.separar() e marcar_disponivel_para_retirada(),
    e a integração com confirmar_saida (que só pega itens já SEPARADO).
    """

    def setUp(self):
        perfil = Perfil.objects.create(nome='Almoxarifado', funcao='ALMOXARIFADO')
        self.usuario = Usuario.objects.create_user(
            cpf='52998224725', nome='Teste', sobrenome='Almoxarifado',
            email='almoxarifado-sep@teste.com', perfil=perfil,
        )
        self.posto = Posto.objects.create(codigo='POSTO-SEP', nome='Posto Separação')
        unidade = UnidadeMedida.objects.create(sigla='UN-SEP', descricao='Unidade Sep')
        self.material = Material.objects.create(
            codigo='MAT-SEP', descricao='Material separação', unidade=unidade,
            estoque_real=Decimal('20'),
        )
        self.solicitacao = Solicitacao.objects.create(
            numero='SOL-SEP-1', posto=self.posto, solicitante=self.usuario,
            data_solicitacao=timezone.now(),
        )
        self.item = ItemSolicitacao.objects.create(
            solicitacao=self.solicitacao, material=self.material,
            quantidade_solicitada=Decimal('10'),
        )
        self.service = SolicitacaoService()

    def test_separar_parcial_mantem_pendente(self):
        self.service.separar(self.item, Decimal('4'))
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade_separada, Decimal('4'))
        self.assertEqual(self.item.status, ItemSolicitacao.Status.PENDENTE)

    def test_separar_completando_vira_separado_e_solicitacao_em_andamento(self):
        self.assertEqual(self.solicitacao.status, Solicitacao.Status.ABERTA)
        self.service.separar(self.item, Decimal('4'))
        self.solicitacao.refresh_from_db()
        self.assertEqual(self.solicitacao.status, Solicitacao.Status.EM_ANDAMENTO)

        self.service.separar(self.item, Decimal('6'))
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade_separada, Decimal('10'))
        self.assertEqual(self.item.status, ItemSolicitacao.Status.SEPARADO)

    def test_separar_quantidade_maior_que_restante_levanta_erro(self):
        with self.assertRaises(SeparacaoInvalidaError):
            self.service.separar(self.item, Decimal('11'))
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade_separada, Decimal('0'))

    def test_separar_sem_estoque_suficiente_levanta_erro(self):
        self.material.estoque_real = Decimal('2')
        self.material.save(update_fields=['estoque_real'])
        with self.assertRaises(DisponibilidadeInsuficienteError):
            self.service.separar(self.item, Decimal('10'))
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade_separada, Decimal('0'))

    def test_marcar_disponivel_para_retirada_com_tudo_separado(self):
        self.service.separar(self.item, Decimal('10'))
        self.service.marcar_disponivel_para_retirada(self.solicitacao)
        self.solicitacao.refresh_from_db()
        self.assertEqual(self.solicitacao.status, Solicitacao.Status.DISPONIVEL_PARA_RETIRADA)

    def test_marcar_disponivel_para_retirada_com_item_pendente_levanta_erro(self):
        self.service.separar(self.item, Decimal('4'))  # parcial, item continua PENDENTE
        with self.assertRaises(DisponivelParaRetiradaInvalidaError):
            self.service.marcar_disponivel_para_retirada(self.solicitacao)
        self.solicitacao.refresh_from_db()
        self.assertNotEqual(self.solicitacao.status, Solicitacao.Status.DISPONIVEL_PARA_RETIRADA)

    def test_confirmar_saida_ignora_item_ainda_pendente(self):
        # item nunca foi separado — confirmar_saida não pega ele
        resultado = self.service.confirmar_saida(
            self.solicitacao, usuario=self.usuario, responsavel_retirada='João Retirada',
        )
        self.assertEqual(resultado, [])
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade_atendida, Decimal('0'))
        self.assertEqual(self.item.status, ItemSolicitacao.Status.PENDENTE)


class SolicitacaoCreateStockValidationTests(TestCase):
    """
    Item não pode nascer numa Solicitação sem estoque suficiente — cobre
    tanto material zerado quanto quantidade pedida maior que o disponível
    (SolicitacaoCreateSerializer.validate_itens).
    """

    def setUp(self):
        perfil = Perfil.objects.create(nome='Almoxarifado', funcao='ALMOXARIFADO')
        self.usuario = Usuario.objects.create_user(
            cpf='11144477735', nome='Teste', sobrenome='Criador',
            email='criador@teste.com', perfil=perfil,
        )
        self.posto = Posto.objects.create(codigo='POSTO-CRIA', nome='Posto Criação')
        unidade = UnidadeMedida.objects.create(sigla='UN-CRIA', descricao='Unidade Criação')
        self.material = Material.objects.create(
            codigo='MAT-CRIA', descricao='Material criação', unidade=unidade,
            estoque_real=Decimal('5'),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.usuario)

    def test_bloqueia_item_com_quantidade_maior_que_estoque(self):
        response = self.client.post('/api/solicitacoes/', {
            'numero': 'SOL-CRIA-1',
            'posto': str(self.posto.id),
            'itens': [
                {'material': str(self.material.id), 'quantidade_solicitada': '6', 'observacao': 'teste'},
            ],
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Solicitacao.objects.filter(numero='SOL-CRIA-1').exists())

    def test_bloqueia_item_de_material_sem_estoque(self):
        self.material.estoque_real = Decimal('0')
        self.material.save(update_fields=['estoque_real'])
        response = self.client.post('/api/solicitacoes/', {
            'numero': 'SOL-CRIA-2',
            'posto': str(self.posto.id),
            'itens': [
                {'material': str(self.material.id), 'quantidade_solicitada': '1', 'observacao': 'teste'},
            ],
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_permite_item_dentro_do_estoque(self):
        response = self.client.post('/api/solicitacoes/', {
            'numero': 'SOL-CRIA-3',
            'posto': str(self.posto.id),
            'itens': [
                {'material': str(self.material.id), 'quantidade_solicitada': '5', 'observacao': 'teste'},
            ],
        }, format='json')
        self.assertEqual(response.status_code, 201)
