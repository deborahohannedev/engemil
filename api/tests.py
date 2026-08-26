from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Material, Perfil, Posto, UnidadeMedida, Usuario
from devolucoes.models import Devolucao
from inventario.models import Inventario
from solicitacoes.models import ItemSolicitacao, Solicitacao


class AlertasResumoTests(TestCase):
    """
    AlertasResumoView é a fonte dos badges de pendência (Solicitação/
    Devolução/Inventário) no menu lateral do frontend — só Almoxarifado e
    quem está em Funcao.SEMPRE_PERMITIDOS (Engenheiro/Administrador) devem
    ver essas contagens.
    """

    def setUp(self):
        self.client = APIClient()
        self.posto = Posto.objects.create(codigo='POSTO-ALERTA', nome='Posto Alerta')
        unidade = UnidadeMedida.objects.create(sigla='UN-ALERTA', descricao='Unidade Alerta')
        self.material = Material.objects.create(
            codigo='MAT-ALERTA', descricao='Material Alerta', unidade=unidade,
            estoque_real=Decimal('100'),
        )

    def _criar_usuario(self, funcao, cpf, sobrenome):
        perfil = Perfil.objects.create(nome=f'Perfil {sobrenome}', funcao=funcao)
        return Usuario.objects.create_user(
            cpf=cpf, nome='Teste', sobrenome=sobrenome, email=f'{sobrenome.lower()}@teste.com', perfil=perfil,
        )

    def test_encarregado_recebe_403(self):
        usuario = self._criar_usuario('ENCARREGADO', '52998224725', 'Encarregado')
        self.client.force_authenticate(usuario)
        response = self.client.get('/api/alertas/resumo/')
        self.assertEqual(response.status_code, 403)

    def test_almoxarifado_recebe_200_com_contadores_corretos(self):
        usuario = self._criar_usuario('ALMOXARIFADO', '52998224725', 'Almoxarifado')
        self.client.force_authenticate(usuario)

        mais_antiga = timezone.now() - timezone.timedelta(days=1)
        mais_recente = timezone.now()
        Solicitacao.objects.create(
            numero='SOL-ALERTA-1', posto=self.posto, solicitante=usuario,
            status=Solicitacao.Status.ABERTA, data_solicitacao=mais_antiga,
        )
        Solicitacao.objects.create(
            numero='SOL-ALERTA-2', posto=self.posto, solicitante=usuario,
            status=Solicitacao.Status.PARCIALMENTE_ATENDIDA, data_solicitacao=mais_recente,
        )
        Solicitacao.objects.create(
            numero='SOL-ALERTA-3', posto=self.posto, solicitante=usuario,
            status=Solicitacao.Status.ATENDIDA, data_solicitacao=timezone.now(),
        )

        response = self.client.get('/api/alertas/resumo/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['solicitacoes']['count'], 2)
        self.assertEqual(response.data['solicitacoes']['mais_recente_em'], mais_recente)

    def test_administrador_bypassa_funcoes_permitidas(self):
        usuario = self._criar_usuario('ADMINISTRADOR', '52998224725', 'Administrador')
        self.client.force_authenticate(usuario)
        response = self.client.get('/api/alertas/resumo/')
        self.assertEqual(response.status_code, 200)

    def test_devolucao_pendente_vs_finalizada(self):
        usuario = self._criar_usuario('ALMOXARIFADO', '52998224725', 'Almoxarifado')
        self.client.force_authenticate(usuario)
        solicitacao = Solicitacao.objects.create(
            numero='SOL-ALERTA-DEV', posto=self.posto, solicitante=usuario, data_solicitacao=timezone.now(),
        )
        item = ItemSolicitacao.objects.create(
            solicitacao=solicitacao, material=self.material, quantidade_solicitada=Decimal('10'),
            quantidade_atendida=Decimal('10'),
        )
        Devolucao.objects.create(
            item_solicitacao=item, responsavel_conferencia=usuario, quantidade=Decimal('2'),
            condicao=True, data_inicial=timezone.now(), data_final=None,
        )
        Devolucao.objects.create(
            item_solicitacao=item, responsavel_conferencia=usuario, quantidade=Decimal('1'),
            condicao=True, decisao=True, data_inicial=timezone.now(), data_final=timezone.now(),
        )

        response = self.client.get('/api/alertas/resumo/')
        self.assertEqual(response.data['devolucoes']['count'], 1)

    def test_dominio_sem_pendencias_retorna_zero_e_null(self):
        usuario = self._criar_usuario('ALMOXARIFADO', '52998224725', 'Almoxarifado')
        self.client.force_authenticate(usuario)
        response = self.client.get('/api/alertas/resumo/')
        self.assertEqual(response.status_code, 200)
        for dominio in ('solicitacoes', 'devolucoes', 'inventarios'):
            self.assertEqual(response.data[dominio]['count'], 0)
            self.assertIsNone(response.data[dominio]['mais_recente_em'])
