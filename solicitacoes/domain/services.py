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


class QuantidadeSaidaSenadoInvalidaError(Exception):
    """
    Levantada quando a quantidade de saída via estoque do Senado informada
    não bate com o que está de fato sendo movimentado nesta confirmação:
    maior que a quantidade movimentada do item, ou informada para um item
    que não entrou no lote desta chamada (já atendido, indisponível, ou
    não pertence à solicitação).
    """
    pass


class SeparacaoInvalidaError(Exception):
    """
    Levantada quando SolicitacaoService.separar() não pode ser executado:
    status da Solicitacao/ItemSolicitacao não aceita separação agora, ou a
    quantidade informada é inválida (<=0 ou maior que o restante a separar).
    """
    pass


class DisponivelParaRetiradaInvalidaError(Exception):
    """
    Levantada quando SolicitacaoService.marcar_disponivel_para_retirada() não
    pode ser executado: a Solicitacao não está num status que aceite essa
    transição, ou nem todo item (não cancelado) está SEPARADO ainda.
    """
    pass


class ResponsavelRetiradaObrigatorioError(Exception):
    """
    Levantada quando confirmar_saida() é chamado sem o nome de quem está
    retirando fisicamente o material — obrigatório, grava em
    Movimentacao.responsavel_retirada pra cada item confirmado.
    """
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
    
    def confirmar_saida(
        self, solicitacao: Solicitacao, usuario: Usuario, responsavel_retirada: str | None = None,
        quantidades_senado: dict | None = None,
    ) -> list:
        """
        Confirma a saída de TODOS os itens pendentes da solicitação que
        estiverem disponíveis. A solicitação só é considerada atendida
        quando TODOS os itens forem atendidos — a criação das
        Movimentacao roda em uma única transação atômica dentro de
        MovimentacaoService.registrar_saida(); se qualquer item falhar
        (quantidade insuficiente), nenhuma saída desta chamada é gravada.

        Só itens já SEPARADO entram nesta chamada — a separação (etapa
        anterior, ver separar()) é pré-requisito, não debita estoque sozinha.
        Itens já INDISPONIVEL não entram nesta chamada — ficam para uma
        nova tentativa de confirmação, depois de reposição de estoque.

        responsavel_retirada: nome de quem está retirando fisicamente o
        material — obrigatório (não é necessariamente um Usuario do
        sistema), grava em Movimentacao.responsavel_retirada pra cada item
        confirmado nesta chamada.

        quantidades_senado (opcional): {item.id: Decimal} com a quantidade,
        dentre a que está sendo movimentada AGORA em cada item, que veio do
        estoque do Senado — ou seja, NÃO saiu do estoque controlado pela
        aplicação. Essa fração fica de fora do débito em Material/Movimentacao:
        só (quantidade_pendente - quantidade_senado) é de fato baixada do
        `estoque_real`. `ItemSolicitacao.quantidade_atendida` continua
        refletindo o total entregue (as duas fontes somadas);
        `quantidade_saida_senado` acumula só a fração do Senado — ambas
        somam entre confirmações parciais.
        """
        if not responsavel_retirada or not responsavel_retirada.strip():
            raise ResponsavelRetiradaObrigatorioError(
                'Informe o nome do responsável pela retirada do material.'
            )
        responsavel_retirada = responsavel_retirada.strip()

        quantidades_senado = dict(quantidades_senado or {})

        itens_pendentes = list(
            solicitacao.itens.filter(status=ItemSolicitacao.Status.SEPARADO)
        )

        if not itens_pendentes:
            return []

        itens_para_movimentar = []
        for item in itens_pendentes:
            quantidade_pendente = item.saldo_pendente()
            if quantidade_pendente <= 0:
                continue

            qtd_senado = quantidades_senado.get(item.id, Decimal('0'))
            if qtd_senado < 0 or qtd_senado > quantidade_pendente:
                raise QuantidadeSaidaSenadoInvalidaError(
                    f'Quantidade via Senado informada para o item {item.material.codigo} '
                    f'inválida: {qtd_senado} (saída pendente: {quantidade_pendente}).'
                )
            # só a fração que NÃO veio do Senado precisa existir no estoque
            # controlado pela aplicação — é isso que de fato sai do Material.
            quantidade_estoque_proprio = quantidade_pendente - qtd_senado

            if not self._saldo_service.verificar_disponibilidade(item.material, quantidade_estoque_proprio):
                item.status = ItemSolicitacao.Status.INDISPONIVEL
                item.save(update_fields=['status'])
                continue

            # só marca a quantidade Senado como "consumida" pelo lote quando o
            # item de fato entra nesta confirmação — item que virou INDISPONIVEL
            # acima deixa a chave intacta, pega pelo check de sobra abaixo.
            quantidades_senado.pop(item.id, None)
            itens_para_movimentar.append(
                (item, item.material, quantidade_pendente, qtd_senado, quantidade_estoque_proprio)
            )

        if quantidades_senado:
            raise QuantidadeSaidaSenadoInvalidaError(
                'Quantidade via Senado informada para item(ns) que não fazem parte '
                'desta confirmação de saída.'
            )

        if not itens_para_movimentar:
            raise DisponibilidadeInsuficienteError(
                'Nenhum item da solicitação está disponível para saída no momento.'
            )

        with transaction.atomic():
            movimentacoes = self._movimentacao_service.registrar_saida(
                solicitacao=solicitacao,
                itens=[
                    (material, qtd_estoque_proprio)
                    for _, material, _, _, qtd_estoque_proprio in itens_para_movimentar
                ],
                usuario=usuario,
                responsavel_retirada=responsavel_retirada,
            )

            for item, _, quantidade_pendente, qtd_senado, _ in itens_para_movimentar:
                item.quantidade_atendida += quantidade_pendente
                item.quantidade_saida_senado += qtd_senado
                item.status = (
                    ItemSolicitacao.Status.ATENDIDO
                    if item.quantidade_atendida >= item.quantidade_solicitada
                    else ItemSolicitacao.Status.DISPONIVEL
                )
                item.save(update_fields=['quantidade_atendida', 'quantidade_saida_senado', 'status'])

            self._atualizar_status_solicitacao(solicitacao)

        return movimentacoes

    def separar(self, item: ItemSolicitacao, quantidade: Decimal) -> ItemSolicitacao:
        """
        Registra separação física de um item — controle administrativo, não
        debita Material.estoque_real (isso só acontece em confirmar_saida).
        Aceita separação parcial: acumula em quantidade_separada e só marca
        o item como SEPARADO quando o total pedido foi separado. Revalida
        disponibilidade a cada chamada — o estoque pode ter mudado desde a
        criação da solicitação (outra solicitação pode ter consumido).
        """
        solicitacao = item.solicitacao
        editaveis = (
            Solicitacao.Status.ABERTA,
            Solicitacao.Status.EM_ANDAMENTO,
            Solicitacao.Status.PARCIALMENTE_ATENDIDA,
        )
        if solicitacao.status not in editaveis:
            raise SeparacaoInvalidaError(
                f'Solicitação com status "{solicitacao.get_status_display()}" não aceita separação de itens.'
            )
        if item.status in (ItemSolicitacao.Status.CANCELADO, ItemSolicitacao.Status.ATENDIDO):
            raise SeparacaoInvalidaError(
                f'Item {item.material.codigo} não pode ser separado '
                f'(status atual: {item.get_status_display()}).'
            )

        falta_separar = item.quantidade_solicitada - item.quantidade_separada
        if falta_separar <= 0:
            raise SeparacaoInvalidaError(f'Item {item.material.codigo} já está totalmente separado.')
        if quantidade <= 0 or quantidade > falta_separar:
            raise SeparacaoInvalidaError(
                f'Quantidade inválida para {item.material.codigo}: informado {quantidade}, '
                f'restam {falta_separar} para separar.'
            )

        if not self._saldo_service.verificar_disponibilidade(item.material, quantidade):
            raise DisponibilidadeInsuficienteError(
                f'Estoque insuficiente para separar {quantidade} de {item.material.codigo}.'
            )

        item.quantidade_separada += quantidade
        item.status = (
            ItemSolicitacao.Status.SEPARADO
            if item.quantidade_separada >= item.quantidade_solicitada
            else ItemSolicitacao.Status.PENDENTE
        )
        item.save(update_fields=['quantidade_separada', 'status'])

        if solicitacao.status == Solicitacao.Status.ABERTA:
            solicitacao.status = Solicitacao.Status.EM_ANDAMENTO
            solicitacao.save(update_fields=['status'])

        return item

    def marcar_disponivel_para_retirada(self, solicitacao: Solicitacao) -> None:
        """
        Transição manual (nunca automática) pra DISPONIVEL_PARA_RETIRADA —
        exige que TODO item não cancelado já esteja SEPARADO.
        """
        editaveis = (
            Solicitacao.Status.ABERTA,
            Solicitacao.Status.EM_ANDAMENTO,
            Solicitacao.Status.PARCIALMENTE_ATENDIDA,
        )
        if solicitacao.status not in editaveis:
            raise DisponivelParaRetiradaInvalidaError(
                f'Solicitação com status "{solicitacao.get_status_display()}" não pode ser '
                f'marcada como disponível para retirada.'
            )

        itens = list(solicitacao.itens.exclude(status=ItemSolicitacao.Status.CANCELADO))
        if not itens or any(item.status != ItemSolicitacao.Status.SEPARADO for item in itens):
            raise DisponivelParaRetiradaInvalidaError(
                'Todos os itens da solicitação precisam estar separados antes de marcar '
                'como disponível para retirada.'
            )

        solicitacao.status = Solicitacao.Status.DISPONIVEL_PARA_RETIRADA
        solicitacao.save(update_fields=['status'])

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

    def reconciliar_status_apos_edicao(self, solicitacao: Solicitacao) -> None:
        """
        Recalcula o status da Solicitacao depois de uma edição de
        cabeçalho/itens (SolicitacaoEditSerializer). Diferente de
        _atualizar_status_solicitacao (chamado só depois de uma tentativa
        real de saída): uma edição pura, sem nenhum item ainda atendido,
        NÃO deve empurrar uma solicitação ABERTA para EM_ANDAMENTO — só
        confirmar-saida faz esse avanço de ciclo. A única transição que
        edição sozinha pode causar é ATENDIDA, no caso raro de editar a
        quantidade de um item já ATENDIDO e isso deixar todos os itens
        atendidos de novo.
        """
        itens = list(solicitacao.itens.all())
        if itens and all(i.status == ItemSolicitacao.Status.ATENDIDO for i in itens):
            novo_status = Solicitacao.Status.ATENDIDA
        elif solicitacao.status == Solicitacao.Status.ABERTA:
            novo_status = Solicitacao.Status.ABERTA
        elif any(i.status == ItemSolicitacao.Status.ATENDIDO for i in itens):
            novo_status = Solicitacao.Status.PARCIALMENTE_ATENDIDA
        else:
            novo_status = Solicitacao.Status.EM_ANDAMENTO

        if novo_status != solicitacao.status:
            solicitacao.status = novo_status
            solicitacao.save(update_fields=['status'])
