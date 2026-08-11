from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from api.permissions import Funcao, PerfilPermission
from api.serializers.core import (
    DemandaSerializer, FornecedorSerializer, MaterialSerializer,
    MovimentacaoSerializer, PerfilSerializer, PostoSerializer,
    ReferenciaTecnicaSerializer, UnidadeMedidaSerializer, UsuarioSerializer,
)
from core.models import (
    Demanda, Fornecedor, Material, Movimentacao,
    Perfil, Posto, ReferenciaTecnica, UnidadeMedida, Usuario,
)


class MaterialViewSet(viewsets.ModelViewSet):
    queryset = Material.objects.all()
    serializer_class = MaterialSerializer
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {
        Funcao.ALMOXARIFADO, Funcao.COMPRAS, Funcao.ENCARREGADO, Funcao.CONSULTA,
    }
    filterset_fields = ['situacao', 'unidade', 'referencia_tecnica']
    search_fields = ['codigo', 'descricao', 'fabricante']


class UnidadeMedidaViewSet(viewsets.ModelViewSet):
    queryset = UnidadeMedida.objects.all()
    serializer_class = UnidadeMedidaSerializer
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {
        Funcao.ALMOXARIFADO, Funcao.COMPRAS, Funcao.ENCARREGADO, Funcao.CONSULTA,
    }


class ReferenciaTecnicaViewSet(viewsets.ModelViewSet):
    queryset = ReferenciaTecnica.objects.all()
    serializer_class = ReferenciaTecnicaSerializer
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {
        Funcao.ALMOXARIFADO, Funcao.COMPRAS, Funcao.ENCARREGADO, Funcao.CONSULTA,
    }


class FornecedorViewSet(viewsets.ModelViewSet):
    queryset = Fornecedor.objects.all()
    serializer_class = FornecedorSerializer
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {Funcao.ALMOXARIFADO, Funcao.COMPRAS}


class DemandaViewSet(viewsets.ModelViewSet):
    queryset = Demanda.objects.all()
    serializer_class = DemandaSerializer
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {
        Funcao.ENCARREGADO, Funcao.ALMOXARIFADO, Funcao.COMPRAS, Funcao.CONSULTA,
    }


class PostoViewSet(viewsets.ModelViewSet):
    queryset = Posto.objects.all()
    serializer_class = PostoSerializer
    permission_classes = [PerfilPermission]
    funcoes_permitidas = set()  # só ADMINISTRADOR/ENGENHEIRO (sempre-permitidos)


class UsuarioViewSet(viewsets.ModelViewSet):
    queryset = Usuario.objects.all()
    serializer_class = UsuarioSerializer
    permission_classes = [PerfilPermission]
    funcoes_permitidas = set()


class PerfilViewSet(viewsets.ModelViewSet):
    queryset = Perfil.objects.all()
    serializer_class = PerfilSerializer
    permission_classes = [PerfilPermission]
    funcoes_permitidas = set()


class MovimentacaoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Movimentacao.objects.all()
    serializer_class = MovimentacaoSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['material', 'tipo', 'usuario']