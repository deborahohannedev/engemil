"""
Domain Service do bounded context devolucoes.

DevolucaoService.aprovar() e .rejeitar() são os ÚNICOS pontos do sistema
autorizados a preencher 'decisao' e 'data_final' em Devolucao.

⚠️ PENDÊNCIAS DE NEGÓCIO (levar para o cliente):
1. rejeitar() nunca gera Movimentacao — material rejeitado nunca volta
   ao estoque, independente do motivo. RN-010 confirma que material
   danificado nunca deve voltar; aprovar() bloqueia esse caso
   explicitamente. Resta confirmar se rejeição por outro motivo (não
   avaria) deveria permitir retorno ao estoque depois.
2. informar() NÃO valida se a quantidade devolvida é maior do que a
   quantidade disponível para devolução. Isso só é barrado tarde, no
   aprovar(), via CheckConstraint do banco — funcional, mas com erro
   pouco amigável.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.domain.services import MovimentacaoService
from core.models import Usuario
from devolucoes.models import Devolucao
from solicitacoes.models import ItemSolicitacao


class MaterialDanificadoNaoRetornaAoEstoqueError(Exception):
    """
    RN-010: material danificado ou sem condição de uso não deve retornar
    ao saldo disponível.
    """
    pass


class DevolucaoJaDecididaError(Exception):
    """Levantada ao tentar aprovar/rejeitar uma devolução que já foi decidida."""
    pass


class DevolucaoService:

    def __init__(self):
        self._movimentacao_service = MovimentacaoService()

    def informar(
        self,
        item_solicitacao: ItemSolicitacao,
        responsavel_conferencia: Usuario,
        quantidade: Decimal,
        condicao: bool,
        observacao: str = '',
    ) -> Devolucao:
        return Devolucao.objects.create(
            item_solicitacao=item_solicitacao,
            responsavel_conferencia=responsavel_conferencia,
            quantidade=quantidade,
            condicao=condicao,
            observacao=observacao,
            data_inicial=timezone.now(),
        )

    def aprovar(self, devolucao: Devolucao, usuario: Usuario) -> None:
        """
        Aprova a devolução, gera a Movimentacao de retorno ao estoque e
        atualiza o cache de quantidade_devolvida no ItemSolicitacao —
        tudo em uma única transação.

        RN-010: material sem condição de uso NUNCA pode ser aprovado
        para retorno ao estoque — só pode ser rejeitado.
        """
        if not devolucao.esta_pendente():
            raise DevolucaoJaDecididaError(
                f'Devolução {devolucao.id} já foi decidida em {devolucao.data_final}.'
            )

        if not devolucao.condicao:
            raise MaterialDanificadoNaoRetornaAoEstoqueError(
                f'Devolução {devolucao.id}: material sem condição de uso não pode ser '
                f'aprovada para retorno ao estoque (RN-010). Use rejeitar() para este caso.'
            )

        with transaction.atomic():
            devolucao.decisao = True
            devolucao.data_final = timezone.now()
            devolucao.save(update_fields=['decisao', 'data_final'])

            self._movimentacao_service.registrar_devolucao(devolucao, usuario)

            item = devolucao.item_solicitacao
            item.quantidade_devolvida += devolucao.quantidade
            item.save(update_fields=['quantidade_devolvida'])

    def rejeitar(self, devolucao: Devolucao, usuario: Usuario, motivo: str = '') -> None:
        """
        Rejeita a devolução. NÃO gera Movimentacao — ver PENDÊNCIA 1 na
        docstring do módulo.
        """
        if not devolucao.esta_pendente():
            raise DevolucaoJaDecididaError(
                f'Devolução {devolucao.id} já foi decidida em {devolucao.data_final}.'
            )

        devolucao.decisao = False
        devolucao.data_final = timezone.now()
        if motivo:
            devolucao.observacao = f'{devolucao.observacao or ""}\n[Rejeição] {motivo}'.strip()
        devolucao.save(update_fields=['decisao', 'data_final', 'observacao'])