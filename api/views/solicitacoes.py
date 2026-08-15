from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.permissions import ApenasProprioSolicitante, Funcao, PerfilPermission
from api.serializers.solicitacoes import SolicitacaoCreateSerializer, SolicitacaoSerializer
from core.domain.services import SaldoInsuficienteError
from solicitacoes.domain.services import (
    DisponibilidadeInsuficienteError, SolicitacaoNaoPodeSerReabertaError, SolicitacaoService,
)
from solicitacoes.models import Solicitacao


class SolicitacaoViewSet(viewsets.ModelViewSet):
    queryset = Solicitacao.objects.all()
    permission_classes = [PerfilPermission, ApenasProprioSolicitante]
    funcoes_permitidas = {Funcao.ENCARREGADO, Funcao.ALMOXARIFADO}
    filterset_fields = ['status', 'posto', 'demanda']
    search_fields = ['numero']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._service = SolicitacaoService()

    def get_queryset(self):
        queryset = Solicitacao.objects.all()
        if self.request.user.perfil.funcao == Funcao.ENCARREGADO:
            return queryset.filter(solicitante=self.request.user)
        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return SolicitacaoCreateSerializer
        return SolicitacaoSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        solicitacao = serializer.save()
        return Response(SolicitacaoSerializer(solicitacao).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def disponibilidade(self, request, pk=None):
        solicitacao = self.get_object()
        resultado = self._service.verificar_disponibilidade(solicitacao)
        return Response({
            str(item.id): disponivel for item, disponivel in resultado.items()
        })

    @action(detail=True, methods=['post'], url_path='confirmar-saida')
    def confirmar_saida(self, request, pk=None):
        if request.user.perfil.funcao not in ({Funcao.ALMOXARIFADO} | Funcao.SEMPRE_PERMITIDOS):
            return Response(
                {'detail': 'Apenas o Almoxarifado pode confirmar saída.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        solicitacao = self.get_object()
        try:
            self._service.confirmar_saida(solicitacao, usuario=request.user)
        except (DisponibilidadeInsuficienteError, SaldoInsuficienteError) as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)

        solicitacao.refresh_from_db()
        return Response(SolicitacaoSerializer(solicitacao).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        solicitacao = self.get_object()
        self._service.cancelar(solicitacao)
        solicitacao.refresh_from_db()
        return Response(SolicitacaoSerializer(solicitacao).data)

    @action(detail=True, methods=['post'])
    def reabrir(self, request, pk=None):
        if request.user.perfil.funcao not in ({Funcao.ALMOXARIFADO} | Funcao.SEMPRE_PERMITIDOS):
            return Response(
                {'detail': 'Apenas o Almoxarifado pode reabrir uma solicitação.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        solicitacao = self.get_object()
        try:
            self._service.reabrir(solicitacao)
        except SolicitacaoNaoPodeSerReabertaError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)

        solicitacao.refresh_from_db()
        return Response(SolicitacaoSerializer(solicitacao).data)