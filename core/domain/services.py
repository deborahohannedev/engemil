"""
Domain Services do bounded context core.

MovimentacaoService é o ÚNICO ponto do sistema autorizado a criar
registros em Movimentacao. Todos os outros apps passam por aqui —
nunca chamam Movimentacao.objects.create() diretamente.

# todo: verificar essa dúvida
⚠️ PENDÊNCIA DE NEGÓCIO (não técnica): o método de custeio de saída
(quanto vale, em R$, uma unidade que sai do estoque) ainda não foi
definido — depende de decisão do cliente/contabilidade (CMP, FIFO, etc.).
Por ora, usamos "custo da última entrada registrada" como placeholder
simples. Ver _custo_unitario_estimado() — é o ÚNICO lugar que precisa
mudar quando a decisão for tomada.
"""
from decimal import Decimal

from django.db import models, transaction

from core.domain.value_objects import OrigemMovimentacao
from core.models import Material, Movimentacao, Usuario


class SaldoInsuficienteError(Exception):
    """Levantada quando uma movimentação resultaria em quantidade física negativa."""
    pass


class MovimentacaoService:

    def registrar_entrada(self, entrada, usuario: Usuario) -> list[Movimentacao]:
        movimentacoes = []
        with transaction.atomic():
            for item in entrada.itens.all():
                origem = OrigemMovimentacao(entrada_id=entrada.id)
                mov = self._criar_movimentacao(
                    material=item.material,
                    origem=origem,
                    usuario=usuario,
                    quantidade_delta=item.quantidade,
                    valor_delta=item.quantidade * item.valor_unitario,
                )
                movimentacoes.append(mov)
        return movimentacoes

    def _criar_movimentacao(
        self,
        material: Material,
        origem: OrigemMovimentacao,
        usuario: Usuario,
        quantidade_delta: Decimal,
        valor_delta: Decimal,
    ) -> Movimentacao:
        with transaction.atomic():
            material = Material.objects.select_for_update().get(pk=material.pk)
            quantidade_anterior = material.estoque_real
            saldo_anterior = self._ultimo_saldo(material)
            quantidade_posterior = quantidade_anterior + quantidade_delta
            saldo_posterior = saldo_anterior + valor_delta

            if quantidade_posterior < 0:
                raise SaldoInsuficienteError(
                    f'Quantidade insuficiente para {material.codigo}: '
                    f'quantidade atual {quantidade_anterior}, tentativa de variação {quantidade_delta}.'
                )

            movimentacao = Movimentacao.objects.create(
                material=material,
                usuario=usuario,
                tipo=origem.tipo,
                quantidade_anterior=quantidade_anterior,
                quantidade_posterior=quantidade_posterior,
                saldo_anterior=saldo_anterior,
                saldo_posterior=saldo_posterior,
                data_movimentacao=self._agora(),
                **origem.as_field_kwargs(),
            )

            material.estoque_real = quantidade_posterior
            material.save(update_fields=['estoque_real'])

        return movimentacao

    def _ultimo_saldo(self, material: Material) -> Decimal:
        """
        Saldo em R$ a partir da última movimentação registrada — só o
        valor monetário ainda não é materializado (só a quantidade, em
        `Material.estoque_real`).

        # todo: validar se pode ser o último registro de movimentação ou se precisa ser o último registro de movimentação do tipo ENTRADA
        # (para não considerar devoluções, por exemplo)
        # e se devolver tem que fazer a movimentação de entrada ou se é só uma movimentação de saída (ou seja, se o saldo do material é afetado ou não)?
        """
        ultima = (
            Movimentacao.objects
            .filter(material=material)
            .order_by('-data_movimentacao')
            .first()
        )
        return ultima.saldo_posterior if ultima else Decimal('0')

    @staticmethod
    def _agora():
        from django.utils import timezone
        return timezone.now()

    def registrar_saida(
        self, solicitacao, itens: list[tuple[Material, Decimal]], usuario: Usuario,
    ) -> list[Movimentacao]:
        """
        itens: lista de (material, quantidade) já validada quanto à
        disponibilidade pela camada de domínio de Solicitacao.
        Todo o loop roda em uma única transação — tudo ou nada.
        """
        movimentacoes = []
        with transaction.atomic():
            for material, quantidade in itens:
                origem = OrigemMovimentacao(solicitacao_id=solicitacao.id)
                custo_unitario = self._custo_unitario_estimado(material)
                mov = self._criar_movimentacao(
                    material=material,
                    origem=origem,
                    usuario=usuario,
                    quantidade_delta=-quantidade,
                    valor_delta=-(quantidade * custo_unitario),
                )
                movimentacoes.append(mov)
        return movimentacoes

    def registrar_devolucao(self, devolucao, usuario: Usuario) -> Movimentacao:
        material = devolucao.item_solicitacao.material
        origem = OrigemMovimentacao(devolucao_id=devolucao.id)
        custo_unitario = self._custo_unitario_estimado(material)
        return self._criar_movimentacao(
            material=material,
            origem=origem,
            usuario=usuario,
            quantidade_delta=devolucao.quantidade,
            valor_delta=devolucao.quantidade * custo_unitario,
        )

    def registrar_ajuste_inventario(self, item_inventario, usuario: Usuario) -> Movimentacao:
        material = item_inventario.material
        origem = OrigemMovimentacao(item_inventario_id=item_inventario.id)
        custo_unitario = self._custo_unitario_estimado(material)
        return self._criar_movimentacao(
            material=material,
            origem=origem,
            usuario=usuario,
            quantidade_delta=item_inventario.ajuste,
            valor_delta=item_inventario.ajuste * custo_unitario,
        )

    def _custo_unitario_estimado(self, material: Material) -> Decimal:
        """
        ⚠️ PLACEHOLDER — método de custeio ainda não definido pelo cliente.

        Implementação atual: custo da ÚLTIMA entrada registrada para este
        material. Não é Custo Médio Ponderado nem FIFO — é uma
        simplificação temporária. Quando a decisão vier, este é o ÚNICO
        método que precisa ser reescrito.
        """
        # todo: validar se pode ser o último registro de entrada ou se precisa ser o último registro de entrada do material 
        # (para não considerar devoluções, por exemplo)
        from entradas.models import ItemEntrada

        ultimo_item_entrada = (
            ItemEntrada.objects
            .filter(material=material)
            .order_by('-entrada__data_entrada')
            .first()
        )
        return ultimo_item_entrada.valor_unitario if ultimo_item_entrada else Decimal('0')


class SaldoEstoqueService:

    def quantidade_atual(self, material: Material) -> Decimal:
        return material.estoque_real

    def estado_atual(self, material: Material) -> tuple[Decimal, Decimal]:
        """
        Retorna (quantidade_atual_em_unidades, saldo_atual_em_reais).
        Quantidade vem de `Material.estoque_real` (materializado pelo
        MovimentacaoService); saldo em R$ ainda vem da última Movimentacao.
        """
        ultima = (
            Movimentacao.objects
            .filter(material=material)
            .order_by('-data_movimentacao')
            .first()
        )
        saldo_atual = ultima.saldo_posterior if ultima else Decimal('0')
        return material.estoque_real, saldo_atual

    def verificar_disponibilidade(self, material: Material, quantidade: Decimal) -> bool:
        return self.quantidade_atual(material) >= quantidade

    def materiais_abaixo_do_minimo(self):
        return Material.objects.filter(
            situacao=Material.Situacao.ATIVO,
            estoque_real__lt=models.F('estoque_minimo'),
        )
