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

from django.db import transaction

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
        quantidade_anterior, saldo_anterior = self._estado_atual(material)
        quantidade_posterior = quantidade_anterior + quantidade_delta
        saldo_posterior = saldo_anterior + valor_delta

        if quantidade_posterior < 0:
            raise SaldoInsuficienteError(
                f'Quantidade insuficiente para {material.codigo}: '
                f'quantidade atual {quantidade_anterior}, tentativa de variação {quantidade_delta}.'
            )

        return Movimentacao.objects.create(
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

    def _estado_atual(self, material: Material) -> tuple[Decimal, Decimal]:
        """
        Retorna (quantidade_atual_em_unidades, saldo_atual_em_reais),
        a partir da última movimentação registrada.

        NOTA DE ARQUITETURA: consulta roda a cada movimentação criada.
        Aceitável para o volume do MVP; avaliar saldo materializado se o
        histórico crescer muito.
        """
        # todo: validar se pode ser o último registro de movimentação ou se precisa ser o último registro de movimentação do tipo ENTRADA 
        # (para não considerar devoluções, por exemplo)
        # e se devolver tem que fazer a movimentação de entrada ou se é só uma movimentação de saída (ou seja, se o saldo do material é afetado ou não)?
        ultima = (
            Movimentacao.objects
            .filter(material=material)
            .order_by('-data_movimentacao')
            .first()
        )
        if ultima is None:
            return Decimal('0'), Decimal('0')
        return ultima.quantidade_posterior, ultima.saldo_posterior

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
        return self.estado_atual(material)[0]

    def estado_atual(self, material: Material) -> tuple[Decimal, Decimal]:
        """
        Retorna (quantidade_atual_em_unidades, saldo_atual_em_reais).
        """
        ultima = (
            Movimentacao.objects
            .filter(material=material)
            .order_by('-data_movimentacao')
            .first()
        )
        if ultima is None:
            return Decimal('0'), Decimal('0')
        return ultima.quantidade_posterior, ultima.saldo_posterior

    def verificar_disponibilidade(self, material: Material, quantidade: Decimal) -> bool:
        return self.quantidade_atual(material) >= quantidade

    def materiais_abaixo_do_minimo(self):
        """
        NOTA: implementação ingênua (itera todo material ativo, calcula
        quantidade um a um). Funciona para o volume do MVP.
        """
        abaixo_do_minimo = []
        for material in Material.objects.filter(situacao=Material.Situacao.ATIVO):
            if self.quantidade_atual(material) < material.estoque_minimo:
                abaixo_do_minimo.append(material)
        return abaixo_do_minimo
