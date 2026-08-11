"""
Permissões da API, baseadas em PERFIL.funcao (documento de visão v1.1,
seção 4.1 — perfis PER-01 a PER-06).

⚠️ PREMISSA ASSUMIDA (confirmar com o cliente): ADMINISTRADOR (PER-05) e
ENGENHEIRO (PER-04) sempre têm acesso, independente da lista de perfis
exigida por view.
"""
from rest_framework.permissions import BasePermission


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

        return funcao_usuario in funcoes_permitidas


class ApenasProprioPosto(BasePermission):
    """
    Permissão de nível de OBJETO: Encarregado (PER-01) só pode
    criar/editar/cancelar solicitações do próprio posto de lotação.
    Espera que o objeto tenha um atributo `.posto` (ex: Solicitacao).
    """

    def has_object_permission(self, request, view, obj):
        if request.user.perfil.funcao != Funcao.ENCARREGADO:
            return True

        return obj.posto_id == request.user.posto_id