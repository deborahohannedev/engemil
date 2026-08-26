from django.db.models import Count, Max
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import Funcao, PerfilPermission
from devolucoes.models import Devolucao
from inventario.models import Inventario
from solicitacoes.models import Solicitacao


class AlertasResumoView(APIView):
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {Funcao.ALMOXARIFADO}

    def get(self, request):
        solicitacoes = Solicitacao.objects.filter(
            status__in=[
                Solicitacao.Status.ABERTA,
                Solicitacao.Status.EM_ANDAMENTO,
                Solicitacao.Status.PARCIALMENTE_ATENDIDA,
            ],
        ).aggregate(count=Count('id'), mais_recente=Max('data_solicitacao'))

        devolucoes = Devolucao.objects.filter(
            data_final__isnull=True,
        ).aggregate(count=Count('id'), mais_recente=Max('data_inicial'))

        inventarios = Inventario.objects.filter(
            situacao=Inventario.Situacao.EM_ANDAMENTO,
        ).aggregate(count=Count('id'), mais_recente=Max('data_inicio'))

        def _formatar(agregado):
            return {'count': agregado['count'], 'mais_recente_em': agregado['mais_recente']}

        return Response({
            'solicitacoes': _formatar(solicitacoes),
            'devolucoes': _formatar(devolucoes),
            'inventarios': _formatar(inventarios),
        })
