import django_filters
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.permissions import ApenasDevolucaoDoProprioSolicitante, Funcao, PerfilPermission
from api.serializers.devolucoes import DevolucaoCreateSerializer, DevolucaoSerializer
from devolucoes.domain.services import (
    DevolucaoJaDecididaError, DevolucaoService,
    MaterialDanificadoNaoRetornaAoEstoqueError, SaldoDevolucaoInsuficienteError,
)
from devolucoes.models import Devolucao


class DevolucaoFilter(django_filters.FilterSet):
    # data_final é datetime (nullable) — "pendente" vira BooleanFilter
    # derivado via isnull, já que esta_pendente() não é um campo de banco.
    pendente = django_filters.BooleanFilter(method='filter_pendente')

    class Meta:
        model = Devolucao
        fields = ['condicao']

    def filter_pendente(self, queryset, name, value):
        return queryset.filter(data_final__isnull=value)


class DevolucaoViewSet(viewsets.ModelViewSet):
    queryset = Devolucao.objects.all()
    permission_classes = [PerfilPermission, ApenasDevolucaoDoProprioSolicitante]
    funcoes_permitidas = {Funcao.ENCARREGADO, Funcao.ALMOXARIFADO}
    filterset_class = DevolucaoFilter
    search_fields = ['item_solicitacao__material__codigo', 'item_solicitacao__material__descricao']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._service = DevolucaoService()

    def get_queryset(self):
        queryset = Devolucao.objects.all()
        if self.request.user.perfil.funcao == Funcao.ENCARREGADO:
            return queryset.filter(item_solicitacao__solicitacao__solicitante=self.request.user)
        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return DevolucaoCreateSerializer
        return DevolucaoSerializer

    def perform_create(self, serializer):
        serializer.save(
            responsavel_conferencia=self.request.user,
            data_inicial=timezone.now(),
        )

    def _checar_almoxarifado(self, request):
        if request.user.perfil.funcao not in ({Funcao.ALMOXARIFADO} | Funcao.SEMPRE_PERMITIDOS):
            return Response(
                {'detail': 'Apenas o Almoxarifado pode decidir sobre devoluções.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def create(self, request, *args, **kwargs):
        from django.utils import timezone

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        devolucao = serializer.save(
            responsavel_conferencia=request.user,
            data_inicial=timezone.now(),
        )
        return Response(DevolucaoSerializer(devolucao).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def aprovar(self, request, pk=None):
        erro = self._checar_almoxarifado(request)
        if erro:
            return erro

        devolucao = self.get_object()
        try:
            self._service.aprovar(devolucao, usuario=request.user)
        except (
            DevolucaoJaDecididaError,
            MaterialDanificadoNaoRetornaAoEstoqueError,
            SaldoDevolucaoInsuficienteError,
        ) as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)

        devolucao.refresh_from_db()
        return Response(DevolucaoSerializer(devolucao).data)

    @action(detail=True, methods=['post'])
    def rejeitar(self, request, pk=None):
        erro = self._checar_almoxarifado(request)
        if erro:
            return erro

        devolucao = self.get_object()
        motivo = request.data.get('motivo', '')
        try:
            self._service.rejeitar(devolucao, usuario=request.user, motivo=motivo)
        except DevolucaoJaDecididaError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)

        devolucao.refresh_from_db()
        return Response(DevolucaoSerializer(devolucao).data)