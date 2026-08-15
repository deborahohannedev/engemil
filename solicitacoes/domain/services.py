"""
Domain Services do bounded context solicitacoes.

SolicitacaoService orquestra o fluxo de saída de materiais, delegando a
criação das Movimentacao para core.domain.services.MovimentacaoService —
nunca cria Movimentacao diretamente.
"""
from decimal import Decimal

from django.db import transaction

from core.domain.services import MovimentacaoService, SaldoEstoqueService
from core.models import Usuario
from solicitacoes.models import ItemSolicitacao, Solicitacao


class DisponibilidadeInsuficienteError(Exception):
    """
    Levantada quando algum item da solicitação não tem quantidade
    disponível em estoque no momento da confirmação de saída.
    """
    pass


class SolicitacaoNaoPodeSerReabertaError(Exception):
    """Levantada ao tentar reabrir uma solicitação que não está ATENDIDA."""
    pass


class SolicitacaoService:

    def __init__(self):
        self._movimentacao_service = MovimentacaoService()
        self._saldo_service = SaldoEstoqueService()

    def verificar_disponibilidade(self, solicitacao: Solicitacao) -> dict:
        """
        Retorna um dict {item: disponivel_bool} para cada item pendente
        da solicitação, sem alterar nenhum estado — só leitura.
        """
        resultado = {}
        for item in solicitacao.itens.exclude(status=ItemSolicitacao.Status.CANCELADO):
            quantidade_pendente = item.saldo_pendente()
            resultado[item] = self._saldo_service.verificar_disponibilidade(
                item.material, quantidade_pendente,
            )
        return resultado
    
    def confirmar_saida(self, solicitacao: Solicitacao, usuario: Usuario) -> list:
        """
        Confirma a saída de TODOS os itens pendentes da solicitação que
        estiverem disponíveis. A solicitação só é considerada atendida
        quando TODOS os itens forem atendidos — a criação das
        Movimentacao roda em uma única transação atômica dentro de
        MovimentacaoService.registrar_saida(); se qualquer item falhar
        (quantidade insuficiente), nenhuma saída desta chamada é gravada.

        Itens já INDISPONIVEL não entram nesta chamada — ficam para uma
        nova tentativa de confirmação, depois de reposição de estoque.
        """
        itens_pendentes = list(
            solicitacao.itens.filter(
                status__in=[ItemSolicitacao.Status.PENDENTE, ItemSolicitacao.Status.DISPONIVEL]
            )
        )

        if not itens_pendentes:
            return []

        itens_para_movimentar = []
        for item in itens_pendentes:
            quantidade_pendente = item.saldo_pendente()
            if quantidade_pendente <= 0:
                continue
            if not self._saldo_service.verificar_disponibilidade(item.material, quantidade_pendente):
                item.status = ItemSolicitacao.Status.INDISPONIVEL
                item.save(update_fields=['status'])
                continue
            itens_para_movimentar.append((item, item.material, quantidade_pendente))

        if not itens_para_movimentar:
            raise DisponibilidadeInsuficienteError(
                'Nenhum item da solicitação está disponível para saída no momento.'
            )

        with transaction.atomic():
            movimentacoes = self._movimentacao_service.registrar_saida(
                solicitacao=solicitacao,
                itens=[(material, qtd) for _, material, qtd in itens_para_movimentar],
                usuario=usuario,
            )

            for item, _, quantidade in itens_para_movimentar:
                item.quantidade_atendida += quantidade
                item.status = (
                    ItemSolicitacao.Status.ATENDIDO
                    if item.quantidade_atendida >= item.quantidade_solicitada
                    else ItemSolicitacao.Status.DISPONIVEL
                )
                item.save(update_fields=['quantidade_atendida', 'status'])

            self._atualizar_status_solicitacao(solicitacao)

        return movimentacoes

    def reabrir(self, solicitacao: Solicitacao) -> None:
        """
        Só é possível reabrir uma solicitação ATENDIDA — volta pra ABERTA
        e marca reaberta_em. Não mexe no status dos itens: eles continuam
        ATENDIDO, então uma nova entrada/edição de itens é que faria a
        solicitação voltar a ter itens pendentes de fato.
        """
        from django.utils import timezone

        if solicitacao.status != Solicitacao.Status.ATENDIDA:
            raise SolicitacaoNaoPodeSerReabertaError(
                f'Solicitação {solicitacao.numero} não pode ser reaberta — status atual é '
                f'"{solicitacao.status}". Só é possível reabrir uma solicitação ATENDIDA.'
            )

        solicitacao.status = Solicitacao.Status.ABERTA
        solicitacao.reaberta_em = timezone.now()
        solicitacao.save(update_fields=['status', 'reaberta_em'])

    def cancelar(self, solicitacao: Solicitacao) -> None:
        solicitacao.itens.exclude(
            status=ItemSolicitacao.Status.ATENDIDO,
        ).update(status=ItemSolicitacao.Status.CANCELADO)
        solicitacao.status = Solicitacao.Status.CANCELADA
        solicitacao.save(update_fields=['status'])

    def _atualizar_status_solicitacao(self, solicitacao: Solicitacao) -> None:
        itens = list(solicitacao.itens.all())
        if all(i.status == ItemSolicitacao.Status.ATENDIDO for i in itens):
            novo_status = Solicitacao.Status.ATENDIDA
        elif any(i.status == ItemSolicitacao.Status.ATENDIDO for i in itens):
            novo_status = Solicitacao.Status.PARCIALMENTE_ATENDIDA
        else:
            novo_status = Solicitacao.Status.EM_ANDAMENTO
        solicitacao.status = novo_status
        solicitacao.save(update_fields=['status'])
