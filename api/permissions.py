"""
Permissões da API, baseadas em PERFIL.funcao (documento de visão v1.1,
seção 4.1 — perfis PER-01 a PER-06).

ADMINISTRADOR (PER-05) e ENGENHEIRO (PER-04) sempre têm acesso irrestrito,
independente da lista de perfis exigida por view — confirmado com o cliente.
COMPRAS (PER-03) e CONSULTA (PER-06) ainda não têm mapeamento de acesso
definido — não aparecem em nenhum `funcoes_permitidas` até isso ser decidido.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission


class Funcao:
    ENCARREGADO = 'ENCARREGADO'      # PER-01
    ALMOXARIFADO = 'ALMOXARIFADO'    # PER-02
    COMPRAS = 'COMPRAS'              # PER-03
    ENGENHEIRO = 'ENGENHEIRO'        # PER-04
    ADMINISTRADOR = 'ADMINISTRADOR'  # PER-05
    CONSULTA = 'CONSULTA'            # PER-06

    SEMPRE_PERMITIDOS = {ADMINISTRADOR, ENGENHEIRO}


class PerfilPermission(BasePermission):
    """
    Permissão de nível de view. Cada view/viewset deve declarar o
    atributo de classe `funcoes_permitidas` (set de strings de Funcao).

    Suporta também o atributo opcional `funcoes_somente_leitura` (set):
    função que estiver nesse set só passa em métodos seguros (GET/HEAD/
    OPTIONS) — usado pra liberar leitura de recursos de apoio (ex.:
    Fornecedor, Demanda, Posto) sem liberar a gestão (criar/editar/excluir).
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        funcoes_permitidas = getattr(view, 'funcoes_permitidas', None)
        if funcoes_permitidas is None:
            raise NotImplementedError(
                f'{view.__class__.__name__} precisa declarar funcoes_permitidas '
                f'para usar PerfilPermission.'
            )

        funcao_usuario = request.user.perfil.funcao

        if funcao_usuario in Funcao.SEMPRE_PERMITIDOS:
            return True

        if funcao_usuario not in funcoes_permitidas:
            return False

        funcoes_somente_leitura = getattr(view, 'funcoes_somente_leitura', set())
        if funcao_usuario in funcoes_somente_leitura and request.method not in SAFE_METHODS:
            return False

        return True


class ApenasProprioSolicitante(BasePermission):
    """
    Permissão de nível de OBJETO: Encarregado (PER-01) só acessa
    Solicitações que ele mesmo criou. Espera objeto com `.solicitante_id`
    (ex.: Solicitacao).
    """

    def has_object_permission(self, request, view, obj):
        if request.user.perfil.funcao != Funcao.ENCARREGADO:
            return True

        return obj.solicitante_id == request.user.id


class ApenasDevolucaoDoProprioSolicitante(BasePermission):
    """
    Permissão de nível de OBJETO: Encarregado (PER-01) só acessa
    Devoluções ligadas a Solicitações que ele mesmo criou.
    """

    def has_object_permission(self, request, view, obj):
        if request.user.perfil.funcao != Funcao.ENCARREGADO:
            return True

        return obj.item_solicitacao.solicitacao.solicitante_id == request.user.id