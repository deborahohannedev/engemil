from decimal import Decimal, InvalidOperation

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.permissions import Funcao, PerfilPermission
from api.serializers.inventario import (
    InventarioCreateSerializer, InventarioSerializer, ItemInventarioSerializer,
)
from core.models import Material, Usuario
from inventario.domain.services import InventarioIncompletoError, InventarioService
from inventario.models import Inventario, ItemInventario


class InventarioViewSet(viewsets.ModelViewSet):
    queryset = Inventario.objects.all()
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {Funcao.ALMOXARIFADO}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._service = InventarioService()

    def get_serializer_class(self):
        if self.action == 'create':
            return InventarioCreateSerializer
        return InventarioSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        material_ids = serializer.validated_data.pop('material_ids')
        materiais = list(Material.objects.filter(id__in=material_ids))

        inventario = self._service.iniciar(
            materiais=materiais,
            observacao=serializer.validated_data.get('observacao', ''),
        )
        return Response(InventarioSerializer(inventario).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def participantes(self, request, pk=None):
        inventario = self.get_object()
        usuario_id = request.data.get('usuario')
        funcao = request.data.get('funcao', '')

        try:
            usuario = Usuario.objects.get(id=usuario_id)
        except Usuario.DoesNotExist:
            return Response({'detail': 'Usuário não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        self._service.adicionar_participante(inventario, usuario, funcao)
        inventario.refresh_from_db()
        return Response(InventarioSerializer(inventario).data)

    @action(detail=True, methods=['post'])
    def encerrar(self, request, pk=None):
        inventario = self.get_object()
        try:
            self._service.encerrar(inventario, usuario=request.user)
        except InventarioIncompletoError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)

        inventario.refresh_from_db()
        return Response(InventarioSerializer(inventario).data)


class ItemInventarioViewSet(viewsets.ModelViewSet):
    """Endpoint dedicado para registrar contagem física item a item (RF-024)."""
    queryset = ItemInventario.objects.all()
    serializer_class = ItemInventarioSerializer
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {Funcao.ALMOXARIFADO}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._service = InventarioService()

    @action(detail=True, methods=['post'], url_path='contagem-fisica')
    @action(detail=True, methods=['post'], url_path='contagem-fisica')
    def contagem_fisica(self, request, pk=None):
        item = self.get_object()
        valor_recebido = request.data.get('quantidade_fisica')

        if valor_recebido is None:
            return Response(
                {'quantidade_fisica': 'Este campo é obrigatório.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            quantidade = Decimal(str(valor_recebido))
        except InvalidOperation:
            return Response(
                {'quantidade_fisica': 'Valor inválido — informe um número.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        self._service.registrar_contagem_fisica(item, quantidade)
        item.refresh_from_db()
        return Response(ItemInventarioSerializer(item).data)