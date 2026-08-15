import django_filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.permissions import Funcao, PerfilPermission
from api.serializers.entradas import EntradaCreateSerializer, EntradaSerializer
from entradas.domain.services import EntradaService
from entradas.models import Entrada
from entradas.domain.services import EntradaJaConfirmadaError, EntradaService


class EntradaFilter(django_filters.FilterSet):
    # confirmada_em é datetime (nullable) — não é um campo de escolha direta
    # pro django-filter, então vira um BooleanFilter derivado via isnull.
    confirmada = django_filters.BooleanFilter(method='filter_confirmada')

    class Meta:
        model = Entrada
        fields = ['fornecedor']

    def filter_confirmada(self, queryset, name, value):
        return queryset.filter(confirmada_em__isnull=not value)


class EntradaViewSet(viewsets.ModelViewSet):
    queryset = Entrada.objects.all()
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {Funcao.ALMOXARIFADO}
    filterset_class = EntradaFilter
    search_fields = ['nota_fiscal']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._service = EntradaService()

    def get_serializer_class(self):
        if self.action == 'create':
            return EntradaCreateSerializer
        return EntradaSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entrada = serializer.save()
        return Response(EntradaSerializer(entrada).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def confirmar(self, request, pk=None):
        entrada = self.get_object()
        try:
            self._service.confirmar(entrada, usuario=request.user)
        except EntradaJaConfirmadaError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(EntradaSerializer(entrada).data)