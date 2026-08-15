from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q

from api.permissions import Funcao, PerfilPermission
from api.serializers.core import (
    DemandaSerializer, FornecedorSerializer, MaterialSerializer,
    MovimentacaoSerializer, PerfilSerializer, PostoSerializer,
    ReferenciaTecnicaSerializer, UnidadeMedidaSerializer, UsuarioSerializer,
    TrocarSenhaSerializer, UsuarioCreateSerializer,
)
from core.models import (
    Demanda, Fornecedor, Material, Movimentacao,
    Perfil, Posto, ReferenciaTecnica, UnidadeMedida, Usuario,
)


class MaterialViewSet(viewsets.ModelViewSet):
    queryset = Material.objects.all()
    serializer_class = MaterialSerializer
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {Funcao.ALMOXARIFADO, Funcao.ENCARREGADO}
    funcoes_somente_leitura = {Funcao.ENCARREGADO}
    filterset_fields = ['situacao', 'unidade', 'referencia_tecnica']
    search_fields = ['codigo', 'descricao', 'fabricante']


class UnidadeMedidaViewSet(viewsets.ModelViewSet):
    queryset = UnidadeMedida.objects.all()
    serializer_class = UnidadeMedidaSerializer
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {Funcao.ALMOXARIFADO}
    funcoes_somente_leitura = {Funcao.ALMOXARIFADO}
    search_fields = ['sigla', 'descricao']


class ReferenciaTecnicaViewSet(viewsets.ModelViewSet):
    queryset = ReferenciaTecnica.objects.all()
    serializer_class = ReferenciaTecnicaSerializer
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {Funcao.ALMOXARIFADO}
    funcoes_somente_leitura = {Funcao.ALMOXARIFADO}
    search_fields = ['codigo', 'nome']


class FornecedorViewSet(viewsets.ModelViewSet):
    queryset = Fornecedor.objects.all()
    serializer_class = FornecedorSerializer
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {Funcao.ALMOXARIFADO}
    funcoes_somente_leitura = {Funcao.ALMOXARIFADO}
    search_fields = ['nome', 'cnpj']


class DemandaViewSet(viewsets.ModelViewSet):
    queryset = Demanda.objects.all()
    serializer_class = DemandaSerializer
    permission_classes = [PerfilPermission]
    funcoes_permitidas = {Funcao.ENCARREGADO, Funcao.ALMOXARIFADO}
    funcoes_somente_leitura = {Funcao.ENCARREGADO, Funcao.ALMOXARIFADO}
    filterset_fields = ['situacao']
    search_fields = ['numero', 'descricao']


class PostoViewSet(viewsets.ModelViewSet):
    queryset = Posto.objects.all()
    serializer_class = PostoSerializer
    permission_classes = [PerfilPermission]
    # leitura liberada pro dropdown de Solicitação — gestão fica só com
    # ADMINISTRADOR/ENGENHEIRO (sempre-permitidos)
    funcoes_permitidas = {Funcao.ENCARREGADO, Funcao.ALMOXARIFADO}
    funcoes_somente_leitura = {Funcao.ENCARREGADO, Funcao.ALMOXARIFADO}
    search_fields = ['codigo', 'nome']


class UsuarioViewSet(viewsets.ModelViewSet):
    queryset = Usuario.objects.all()
    permission_classes = [PerfilPermission]
    funcoes_permitidas = set()
    filterset_fields = ['situacao', 'perfil']
    search_fields = ['nome', 'sobrenome', 'cpf', 'email']

    def get_serializer_class(self):
        if self.action == 'create':
            return UsuarioCreateSerializer
        return UsuarioSerializer

    @action(detail=False, methods=['get'], url_path='me', permission_classes=[IsAuthenticated])
    def me(self, request):
        serializer = UsuarioSerializer(request.user)
        return Response(serializer.data)

    @action(detail=False, methods=['post'], url_path='trocar-senha', permission_classes=[IsAuthenticated])
    def trocar_senha(self, request):
        serializer = TrocarSenhaSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'detail': 'Senha atualizada com sucesso.'})

    @action(detail=True, methods=['post'], url_path='resetar-senha')
    def resetar_senha(self, request, pk=None):
        from core.models import gerar_senha_temporaria

        usuario = self.get_object()
        nova_senha = gerar_senha_temporaria()
        usuario.set_password(nova_senha)
        usuario.senha_temporaria = True
        usuario.save(update_fields=['password', 'senha_temporaria'])

        return Response({'senha_gerada': nova_senha})


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
    search_fields = ['material__codigo', 'material__descricao']

    def get_queryset(self):
        queryset = Movimentacao.objects.all()
        if self.request.user.perfil.funcao == Funcao.ENCARREGADO:
            return queryset.filter(
                tipo__in=[Movimentacao.Tipo.SAIDA, Movimentacao.Tipo.DEVOLUCAO],
            ).filter(
                Q(solicitacao__solicitante=self.request.user) |
                Q(devolucao__item_solicitacao__solicitacao__solicitante=self.request.user)
            )
        return queryset
