"""
Value Objects do bounded context core.

Objetos imutáveis, sem identidade própria, que encapsulam invariantes de
negócio — validados no momento da CONSTRUÇÃO, não em um método separado
que alguém poderia esquecer de chamar.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from uuid import UUID


class TipoMovimentacao(str, Enum):
    ENTRADA = 'ENTRADA'
    SAIDA = 'SAIDA'
    DEVOLUCAO = 'DEVOLUCAO'
    AJUSTE_INVENTARIO = 'AJUSTE_INVENTARIO'


@dataclass(frozen=True)
class OrigemMovimentacao:
    """
    Representa a origem de uma Movimentacao. Garante, na construção,
    que exatamente uma das 4 origens possíveis está preenchida — é a
    tradução em código da regra de negócio que também existe como
    CheckConstraint em core.models.Movimentacao (defesa em profundidade).

    Impossível instanciar um OrigemMovimentacao inválido: o erro acontece
    aqui, em Python, antes de qualquer tentativa de gravar no banco.
    """

    solicitacao_id: Optional[UUID] = None
    entrada_id: Optional[UUID] = None
    devolucao_id: Optional[UUID] = None
    item_inventario_id: Optional[UUID] = None

    def __post_init__(self):
        preenchidos = [
            self.solicitacao_id,
            self.entrada_id,
            self.devolucao_id,
            self.item_inventario_id,
        ]
        quantidade_preenchida = sum(1 for campo in preenchidos if campo is not None)

        if quantidade_preenchida != 1:
            raise ValueError(
                'OrigemMovimentacao deve ter exatamente uma origem preenchida, '
                f'encontradas {quantidade_preenchida}.'
            )

    @property
    def tipo(self) -> TipoMovimentacao:
        if self.entrada_id is not None:
            return TipoMovimentacao.ENTRADA
        if self.solicitacao_id is not None:
            return TipoMovimentacao.SAIDA
        if self.devolucao_id is not None:
            return TipoMovimentacao.DEVOLUCAO
        if self.item_inventario_id is not None:
            return TipoMovimentacao.AJUSTE_INVENTARIO
        raise RuntimeError('Estado inválido de OrigemMovimentacao.')

    def as_field_kwargs(self) -> dict:
        return {
            'solicitacao_id': self.solicitacao_id,
            'entrada_id': self.entrada_id,
            'devolucao_id': self.devolucao_id,
            'item_inventario_id': self.item_inventario_id,
        }