import uuid

from django.db import models


class Devolucao(models.Model):
    """
    'decisao' e 'data_final' juntos representam um estado de 3 posições
    sem precisar de um enum: enquanto data_final for NULL, a devolução
    está PENDENTE e 'decisao' não deve ser interpretado como resposta
    final (é apenas o valor padrão até a conferência acontecer). Só
    depois que data_final é preenchido é que 'decisao' passa a valer
    como aprovada (True) ou rejeitada (False).

    NUNCA leia 'decisao' isoladamente para saber o resultado — sempre
    cheque 'esta_pendente()' primeiro.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item_solicitacao = models.ForeignKey(
        'solicitacoes.ItemSolicitacao', on_delete=models.PROTECT, related_name='devolucoes',
    )
    responsavel_conferencia = models.ForeignKey(
        'core.Usuario', on_delete=models.PROTECT, related_name='devolucoes_conferidas',
    )
    quantidade = models.DecimalField(max_digits=14, decimal_places=3)

    # True = material em condição de uso; False = danificado/inutilizável
    condicao = models.BooleanField()

    # Ver docstring da classe — não interpretar sem checar data_final antes
    decisao = models.BooleanField(default=False)

    observacao = models.TextField(null=True, blank=True)
    data_inicial = models.DateTimeField()
    data_final = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'devolucao'
        ordering = ['-data_inicial']
        constraints = [
            models.CheckConstraint(
                check=models.Q(quantidade__gt=0),
                name='ck_devolucao_quantidade_positiva',
            ),
        ]

    def __str__(self):
        return f'Devolução {str(self.id)[:8]} — {self.item_solicitacao.material.codigo}'

    def esta_pendente(self) -> bool:
        return self.data_final is None