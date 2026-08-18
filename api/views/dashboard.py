from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Material
from solicitacoes.models import ItemSolicitacao, Solicitacao


class DashboardResumoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        valor_field = DecimalField(max_digits=18, decimal_places=2)

        saldo_estoque = Material.objects.filter(
            valor_unitario__isnull=False,
        ).aggregate(
            total=Sum(
                ExpressionWrapper(F('estoque_real') * F('valor_unitario'), output_field=valor_field),
            ),
        )['total'] or Decimal('0')

        # valor total solicitado (quantidade_solicitada × valor_unitario cadastral)
        # dos itens de solicitações já ATENDIDAS — mesmo cálculo do
        # SolicitacaoSerializer.get_valor_total, só filtrado por status.
        saldo_solicitacoes_atendidas = ItemSolicitacao.objects.filter(
            solicitacao__status=Solicitacao.Status.ATENDIDA,
            material__valor_unitario__isnull=False,
        ).aggregate(
            total=Sum(
                ExpressionWrapper(
                    F('quantidade_solicitada') * F('material__valor_unitario'), output_field=valor_field,
                ),
            ),
        )['total'] or Decimal('0')

        return Response({
            'saldo_estoque': saldo_estoque,
            'saldo_solicitacoes_atendidas': saldo_solicitacoes_atendidas,
            'saldo_total': saldo_estoque + saldo_solicitacoes_atendidas,
        })
