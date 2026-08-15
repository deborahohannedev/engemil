"""
Domain Service do bounded context devolucoes.

DevolucaoService.aprovar() e .rejeitar() são os ÚNICOS pontos do sistema
autorizados a preencher 'decisao' e 'data_final' em Devolucao.

⚠️ PENDÊNCIA DE NEGÓCIO (levar para o cliente):
1. rejeitar() nunca gera Movimentacao — material rejeitado nunca volta
   ao estoque, independente do motivo. RN-010 confirma que material
   danificado nunca deve voltar; aprovar() bloqueia esse caso
   explicitamente. Resta confirmar se rejeição por outro motivo (não
   avaria) deveria permitir retorno ao estoque depois.

Regras já garantidas em DevolucaoCreateSerializer.validate() (espelhadas
aqui em informar() como defesa em profundidade, já que a view hoje cria
Devolucao direto pelo serializer, sem passar por este service):
- só uma devolução em aberto por item por vez (DevolucaoJaAbertaError)
- quantidade não pode passar do disponível (quantidade_atendida -
  quantidade_devolvida), sempre recalculado na hora do submit

aprovar() repete essa mesma checagem de saldo (SaldoDevolucaoInsuficienteError)
— bug real corrigido: sem isso, uma devolução pendente criada antes de outra
já ter sido aprovada (esvaziando o saldo) estourava IntegrityError seco
(ck_item_solicitacao_devolvida_lte_atendida) ao tentar aprovar, virando 500.
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


class DevolucaoJaAbertaError(Exception):
    """
    Levantada ao tentar informar uma devolução pra um item que já tem
    outra devolução pendente (data_final IS NULL). Só pode existir uma
    devolução em aberto por item — a próxima só pode ser aberta depois
    que a anterior for aprovada ou rejeitada.
    """
    pass


class SaldoDevolucaoInsuficienteError(Exception):
    """Levantada ao tentar devolver mais do que quantidade_atendida - quantidade_devolvida."""
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
        if item_solicitacao.devolucoes.filter(data_final__isnull=True).exists():
            raise DevolucaoJaAbertaError(
                f'Item {item_solicitacao.material.codigo} já tem uma devolução pendente. '
                f'Aguarde ela ser aprovada ou rejeitada antes de abrir outra.'
            )

        disponivel = item_solicitacao.quantidade_atendida - item_solicitacao.quantidade_devolvida
        if quantidade > disponivel:
            raise SaldoDevolucaoInsuficienteError(
                f'Quantidade devolvida ({quantidade}) não pode passar do disponível ({disponivel}).'
            )

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

        item = devolucao.item_solicitacao
        disponivel = item.quantidade_atendida - item.quantidade_devolvida
        if devolucao.quantidade > disponivel:
            raise SaldoDevolucaoInsuficienteError(
                f'Devolução {devolucao.id}: quantidade ({devolucao.quantidade}) não cabe mais no '
                f'disponível do item ({disponivel}) — aprovar violaria a constraint do banco. '
                f'Rejeite esta devolução.'
            )

        with transaction.atomic():
            devolucao.decisao = True
            devolucao.data_final = timezone.now()
            devolucao.save(update_fields=['decisao', 'data_final'])

            self._movimentacao_service.registrar_devolucao(devolucao, usuario)

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