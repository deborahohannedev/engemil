from decimal import Decimal, InvalidOperation

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse

from api.permissions import Funcao, PerfilPermission
from api.serializers.inventario import (
    InventarioCreateSerializer, InventarioSerializer, ItemInventarioSerializer,
)
from core.models import Usuario
from core.validators import validar_quantidade_por_unidade
from inventario.domain.relatorio import gerar_laudo_pdf
from inventario.domain.services import InventarioService
from inventario.models import Inventario, ItemInventario


class InventarioViewSet(viewsets.ModelViewSet):
    queryset = Inventario.objects.all()
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {Funcao.ALMOXARIFADO}
    filterset_fields = ['situacao']

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

        inventario = self._service.iniciar(
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
        self._service.encerrar(inventario, usuario=request.user)
        inventario.refresh_from_db()
        return Response(InventarioSerializer(inventario).data)

    @action(detail=True, methods=['get'])
    def laudo(self, request, pk=None):
        inventario = self.get_object()
        pdf_bytes = gerar_laudo_pdf(inventario)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="laudo-inventario-{inventario.id}.pdf"'
        return response


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

        try:
            validar_quantidade_por_unidade(quantidade, item.material.unidade)
        except DjangoValidationError as exc:
            return Response({'quantidade_fisica': exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        self._service.registrar_contagem_fisica(item, quantidade)
        item.refresh_from_db()
        return Response(ItemInventarioSerializer(item).data)