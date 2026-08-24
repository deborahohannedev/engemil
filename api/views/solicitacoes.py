from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.permissions import ApenasProprioSolicitante, Funcao, PerfilPermission
from api.serializers.solicitacoes import (
    ItemSaidaSenadoInputSerializer, ItemSepararInputSerializer, ItemSolicitacaoSerializer,
    SolicitacaoCreateSerializer, SolicitacaoEditSerializer, SolicitacaoSerializer,
)
from core.domain.services import SaldoInsuficienteError
from solicitacoes.domain.services import (
    DisponibilidadeInsuficienteError, DisponivelParaRetiradaInvalidaError,
    QuantidadeSaidaSenadoInvalidaError, ResponsavelRetiradaObrigatorioError,
    SeparacaoInvalidaError, SolicitacaoService,
)
from solicitacoes.models import ItemSolicitacao, Solicitacao


class SolicitacaoViewSet(viewsets.ModelViewSet):
    queryset = Solicitacao.objects.all()
    permission_classes = [PerfilPermission, ApenasProprioSolicitante]
    funcoes_permitidas = {Funcao.ENCARREGADO, Funcao.ALMOXARIFADO}
    filterset_fields = ['status', 'posto']
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
        if self.action in ('update', 'partial_update'):
            return SolicitacaoEditSerializer
        return SolicitacaoSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        solicitacao = serializer.save()
        return Response(SolicitacaoSerializer(solicitacao).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        # Edição de cabeçalho + itens (Encarregado dono / Almoxarifado /
        # Administrador / Engenheiro) — só permitida em status ABERTA,
        # EM_ANDAMENTO ou PARCIALMENTE_ATENDIDA; validado dentro de
        # SolicitacaoEditSerializer, não aqui.
        partial = kwargs.pop('partial', False)
        solicitacao = self.get_object()
        serializer = self.get_serializer(solicitacao, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        solicitacao = serializer.save()
        return Response(SolicitacaoSerializer(solicitacao).data)

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

        itens_senado_serializer = ItemSaidaSenadoInputSerializer(
            data=request.data.get('itens_senado', []), many=True,
        )
        itens_senado_serializer.is_valid(raise_exception=True)
        quantidades_senado = {
            dados['item']: dados['quantidade'] for dados in itens_senado_serializer.validated_data
        }

        try:
            self._service.confirmar_saida(
                solicitacao, usuario=request.user,
                responsavel_retirada=request.data.get('responsavel_retirada'),
                quantidades_senado=quantidades_senado,
            )
        except (DisponibilidadeInsuficienteError, SaldoInsuficienteError) as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        except (QuantidadeSaidaSenadoInvalidaError, ResponsavelRetiradaObrigatorioError) as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        solicitacao.refresh_from_db()
        return Response(SolicitacaoSerializer(solicitacao).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        solicitacao = self.get_object()
        self._service.cancelar(solicitacao)
        solicitacao.refresh_from_db()
        return Response(SolicitacaoSerializer(solicitacao).data)

    @action(detail=True, methods=['post'], url_path='disponivel-para-retirada')
    def disponivel_para_retirada(self, request, pk=None):
        if request.user.perfil.funcao not in ({Funcao.ALMOXARIFADO} | Funcao.SEMPRE_PERMITIDOS):
            return Response(
                {'detail': 'Apenas o Almoxarifado pode marcar como disponível para retirada.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        solicitacao = self.get_object()
        try:
            self._service.marcar_disponivel_para_retirada(solicitacao)
        except DisponivelParaRetiradaInvalidaError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)

        solicitacao.refresh_from_db()
        return Response(SolicitacaoSerializer(solicitacao).data)


class ItemSolicitacaoViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Endpoint dedicado à etapa de separação, item a item (ver
    SolicitacaoService.separar()). De propósito NÃO é um ModelViewSet — só
    retrieve + a action `separar`, pra não abrir um caminho de escrita
    direta em campos como `material`/`quantidade_solicitada` que
    contornaria as validações de SolicitacaoCreateSerializer/EditSerializer.
    """
    queryset = ItemSolicitacao.objects.all()
    serializer_class = ItemSolicitacaoSerializer
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {Funcao.ALMOXARIFADO}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._service = SolicitacaoService()

    @action(detail=True, methods=['post'])
    def separar(self, request, pk=None):
        item = self.get_object()
        serializer = ItemSepararInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            self._service.separar(item, serializer.validated_data['quantidade'])
        except SeparacaoInvalidaError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except DisponibilidadeInsuficienteError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)

        item.refresh_from_db()
        return Response(ItemSolicitacaoSerializer(item).data)