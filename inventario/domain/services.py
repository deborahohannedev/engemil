"""
Domain Service do bounded context inventario.

InventarioService.encerrar() é o ÚNICO ponto autorizado a preencher
encerrado_em/encerrado_por em Inventario e a disparar os ajustes de
estoque resultantes da contagem.

⚠️ PREMISSAS ASSUMIDAS (confirmar com o cliente):
1. encerrar() exige que TODOS os itens tenham sido contados antes de
   permitir o encerramento.
2. Todo item com divergência gera automaticamente um ajuste de estoque
   igual à divergência integral, sem etapa de aprovação item a item.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.domain.services import MovimentacaoService, SaldoEstoqueService
from core.models import Material, Usuario
from inventario.models import Inventario, ItemInventario, ParticipanteInventario


class InventarioIncompletoError(Exception):
    """Levantada ao tentar encerrar um inventário com itens não contados."""
    pass


class InventarioService:

    def __init__(self):
        self._movimentacao_service = MovimentacaoService()
        self._saldo_service = SaldoEstoqueService()


    def iniciar(self, materiais: list, observacao: str = '') -> Inventario:
        """
        Cria o inventário e já gera um ItemInventario para cada material
        informado, capturando a quantidade/saldo do sistema no momento
        do início da contagem (snapshot).
        """
        with transaction.atomic():
            inventario = Inventario.objects.create(
                data_inicio=timezone.now(),
                observacao=observacao,
            )
            for material in materiais:
                quantidade_atual, saldo_atual = self._saldo_service.estado_atual(material)
                ItemInventario.objects.create(
                    inventario=inventario,
                    material=material,
                    quantidade_sistema=quantidade_atual,
                    saldo_sistema=saldo_atual,
                )
        return inventario

    def adicionar_participante(
        self, inventario: Inventario, usuario: Usuario, funcao: str,
    ) -> ParticipanteInventario:
        return ParticipanteInventario.objects.create(
            inventario=inventario, usuario=usuario, funcao=funcao,
        )

    def registrar_contagem_fisica(
        self, item: ItemInventario, quantidade_fisica: Decimal,
    ) -> ItemInventario:
        item.quantidade_fisica = quantidade_fisica
        item.calcular_divergencia()
        item.save(update_fields=['quantidade_fisica', 'divergencia'])
        return item

    def encerrar(self, inventario: Inventario, usuario: Usuario) -> list:
        """
        Encerra o inventário: valida que todos os itens foram contados,
        gera Movimentacao de ajuste para cada item com divergência, e
        marca o inventário como ENCERRADO. Tudo em uma única transação.
        """
        itens = list(inventario.itens.all())

        nao_contados = [item for item in itens if not item.foi_contado()]
        if nao_contados:
            codigos = ', '.join(item.material.codigo for item in nao_contados)
            raise InventarioIncompletoError(
                f'Inventário possui {len(nao_contados)} item(ns) não contado(s): {codigos}.'
            )

        movimentacoes = []
        with transaction.atomic():
            for item in itens:
                divergencia = item.calcular_divergencia()
                if divergencia and divergencia != 0:
                    item.ajuste = divergencia
                    item.save(update_fields=['divergencia', 'ajuste'])
                    mov = self._movimentacao_service.registrar_ajuste_inventario(item, usuario)
                    movimentacoes.append(mov)
                else:
                    item.save(update_fields=['divergencia'])

            inventario.situacao = Inventario.Situacao.ENCERRADO
            inventario.data_fim = timezone.now()
            inventario.encerrado_em = timezone.now()
            inventario.encerrado_por = usuario
            inventario.save(
                update_fields=['situacao', 'data_fim', 'encerrado_em', 'encerrado_por']
            )

        return movimentacoes