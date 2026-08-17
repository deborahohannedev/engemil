"""
Domain Service do bounded context inventario.

InventarioService.encerrar() é o ÚNICO ponto autorizado a preencher
encerrado_em/encerrado_por em Inventario e a disparar os ajustes de
estoque resultantes da contagem.

⚠️ PREMISSA ASSUMIDA (confirmar com o cliente):
- Todo item com divergência gera automaticamente um ajuste de estoque
  igual à divergência integral, sem etapa de aprovação item a item.

Item não contado manualmente antes do encerramento: quantidade física
assumida = quantidade do sistema (sem divergência) — decisão da
Deborah, encerrar() não fica mais bloqueado esperando 100% dos itens
contados.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.domain.services import MovimentacaoService, SaldoEstoqueService, SaldoInsuficienteError
from core.models import Material, Usuario
from inventario.models import Inventario, ItemInventario, ParticipanteInventario


class InventarioService:

    def __init__(self):
        self._movimentacao_service = MovimentacaoService()
        self._saldo_service = SaldoEstoqueService()


    # ⚠️ LIMITE TEMPORÁRIO PRA DEMO (MVP) — ver TODO.md item 9. A regra de
    # negócio real é TODOS os materiais ATIVO; isso está artificialmente
    # limitado aos 10 primeiros (por `codigo`) porque a tela ainda não
    # aguenta bem ~979 itens de uma vez (contagem/salvamento ficando
    # lento/travando). Reverter pra `[:LIMITE_TEMPORARIO_DEMO]` → sem
    # limite assim que a otimização de performance for feita.
    LIMITE_TEMPORARIO_DEMO = 10

    def iniciar(self, observacao: str = '') -> Inventario:
        """
        Cria o inventário incluindo automaticamente os materiais com
        situação ATIVO — não é mais uma seleção manual (pedido do cliente:
        o inventário sempre parte da base completa de materiais ativos).
        Já gera um ItemInventario por material, capturando a
        quantidade/saldo do sistema no momento do início da contagem
        (snapshot).

        NOTA: por ora limitado aos primeiros `LIMITE_TEMPORARIO_DEMO`
        materiais — ver comentário acima da constante.
        """
        materiais = Material.objects.filter(
            situacao=Material.Situacao.ATIVO,
        )[:self.LIMITE_TEMPORARIO_DEMO]
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
        self, item: ItemInventario, quantidade_fisica: Decimal, observacao: str | None = None,
    ) -> ItemInventario:
        """
        `observacao` é opcional e de uso livre de quem está contando (ex.:
        "embalagem violada", "contei de novo, valor confirmado") — só é
        alterada se vier explicitamente no request (`None` = campo não
        enviado, mantém o que já estava salvo). Sistema também escreve
        nesse mesmo campo em casos de erro (ver
        InventarioService.encerrar()), sempre concatenando em vez de
        sobrescrever — ver o padrão em DevolucaoService.rejeitar().
        """
        item.quantidade_fisica = quantidade_fisica
        item.calcular_divergencia()
        campos = ['quantidade_fisica', 'divergencia']
        if observacao is not None:
            item.observacao = observacao
            campos.append('observacao')
        item.save(update_fields=campos)
        return item

    def encerrar(self, inventario: Inventario, usuario: Usuario) -> tuple[list, list]:
        """
        Encerra o inventário: item que não foi contado manualmente recebe
        quantidade_fisica = quantidade_sistema automaticamente (sem
        divergência) — encerrar não fica bloqueado esperando 100% dos
        itens contados. Gera Movimentacao de ajuste para cada item com
        divergência, e marca o inventário como ENCERRADO.

        `quantidade_sistema` é um retrato tirado no início do inventário
        (ver iniciar()) — se o inventário demora pra ser encerrado,
        outras movimentações (saídas, entradas...) podem já ter alterado
        o saldo REAL do material nesse meio-tempo. Isso pode fazer o
        ajuste calculado contra o retrato antigo não caber mais no saldo
        atual (SaldoInsuficienteError). Decisão: isso NÃO derruba o
        encerramento inteiro — o item fica com o ajuste marcado como não
        aplicado (fica registrado na observação do item, visível na tela
        e no laudo) pra resolução manual depois, e o inventário encerra
        normalmente com os demais itens.
        """
        itens = list(inventario.itens.all())

        movimentacoes = []
        itens_com_pendencia = []
        with transaction.atomic():
            for item in itens:
                if not item.foi_contado():
                    item.quantidade_fisica = item.quantidade_sistema

                divergencia = item.calcular_divergencia()
                if divergencia and divergencia != 0:
                    item.ajuste = divergencia
                    try:
                        with transaction.atomic():
                            item.save(update_fields=['quantidade_fisica', 'divergencia', 'ajuste'])
                            mov = self._movimentacao_service.registrar_ajuste_inventario(item, usuario)
                            movimentacoes.append(mov)
                    except SaldoInsuficienteError as exc:
                        item.ajuste = None
                        nota = (
                            f'[Ajuste não aplicado] {exc} Divergência calculada de {divergencia} '
                            f'não coube no saldo atual do material — provavelmente outras '
                            f'movimentações aconteceram depois do início deste inventário. '
                            f'Resolver manualmente.'
                        )
                        item.observacao = f'{item.observacao or ""}\n{nota}'.strip()
                        item.save(update_fields=['quantidade_fisica', 'divergencia', 'ajuste', 'observacao'])
                        itens_com_pendencia.append(item)
                else:
                    item.save(update_fields=['quantidade_fisica', 'divergencia'])

            inventario.situacao = Inventario.Situacao.ENCERRADO
            inventario.data_fim = timezone.now()
            inventario.encerrado_em = timezone.now()
            inventario.encerrado_por = usuario
            inventario.save(
                update_fields=['situacao', 'data_fim', 'encerrado_em', 'encerrado_por']
            )

        return movimentacoes, itens_com_pendencia