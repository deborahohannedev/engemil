"""
Domain Service do bounded context entradas.
"""
from core.domain.services import MovimentacaoService
from core.models import Usuario
from entradas.models import Entrada


class EntradaService:

    def __init__(self):
        self._movimentacao_service = MovimentacaoService()

    def confirmar(self, entrada: Entrada, usuario: Usuario) -> list:
        """
        Confirma a entrada, gerando uma Movimentacao por item — delegado
        inteiramente ao MovimentacaoService, que já roda em transação
        atômica.
        """
        if not entrada.itens.exists():
            raise ValueError('Entrada sem itens não pode ser confirmada.')

        return self._movimentacao_service.registrar_entrada(entrada, usuario)