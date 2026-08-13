"""
Domain Service do bounded context entradas.
"""
from core.domain.services import MovimentacaoService
from core.models import Usuario
from entradas.models import Entrada


class EntradaJaConfirmadaError(Exception):
    """Levantada ao tentar confirmar uma entrada que já foi confirmada."""
    pass

class EntradaService:

    def __init__(self):
        self._movimentacao_service = MovimentacaoService()

    def confirmar(self, entrada: Entrada, usuario: Usuario) -> list:
        """
        Confirma a entrada, gerando uma Movimentacao por item — delegado
        inteiramente ao MovimentacaoService, que já roda em transação
        atômica.

        Uma entrada só pode ser confirmada uma vez — confirmar_em nulo é
        o único jeito de saber que ainda não foi processada.
        """
        from django.utils import timezone

        if entrada.esta_confirmada():
            raise EntradaJaConfirmadaError(
                f'Entrada {entrada.id} já foi confirmada em {entrada.confirmada_em}.'
            )

        if not entrada.itens.exists():
            raise ValueError('Entrada sem itens não pode ser confirmada.')

        movimentacoes = self._movimentacao_service.registrar_entrada(entrada, usuario)

        entrada.confirmada_em = timezone.now()
        entrada.save(update_fields=['confirmada_em'])

        return movimentacoes