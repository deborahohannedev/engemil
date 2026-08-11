import uuid

from django.db import models


class Solicitacao(models.Model):

    class Status(models.TextChoices):
        ABERTA = 'ABERTA', 'Aberta'
        EM_ANDAMENTO = 'EM_ANDAMENTO', 'Em andamento'
        PARCIALMENTE_ATENDIDA = 'PARCIALMENTE_ATENDIDA', 'Parcialmente atendida'
        ATENDIDA = 'ATENDIDA', 'Atendida'
        CANCELADA = 'CANCELADA', 'Cancelada'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    numero = models.CharField(max_length=30, unique=True)
    status = models.CharField(max_length=25, choices=Status.choices, default=Status.ABERTA)
    data_solicitacao = models.DateTimeField()
    data_prevista = models.DateTimeField()

    demanda = models.ForeignKey(
        'core.Demanda', on_delete=models.PROTECT, related_name='solicitacoes',
    )
    posto = models.ForeignKey(
        'core.Posto', on_delete=models.PROTECT, related_name='solicitacoes',
    )
    solicitante = models.ForeignKey(
        'core.Usuario', on_delete=models.PROTECT, related_name='solicitacoes_criadas',
    )
    observacao = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'solicitacao'
        ordering = ['-data_solicitacao']
        constraints = [
            models.CheckConstraint(
                check=models.Q(data_prevista__gte=models.F('data_solicitacao')),
                name='ck_solicitacao_datas',
            ),
        ]

    def __str__(self):
        return self.numero

    def esta_totalmente_atendida(self) -> bool:
        return all(
            item.status == ItemSolicitacao.Status.ATENDIDO
            for item in self.itens.all()
        )


class ItemSolicitacao(models.Model):

    class Status(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Pendente'
        DISPONIVEL = 'DISPONIVEL', 'Disponível'
        INDISPONIVEL = 'INDISPONIVEL', 'Indisponível'
        ATENDIDO = 'ATENDIDO', 'Atendido'
        CANCELADO = 'CANCELADO', 'Cancelado'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    solicitacao = models.ForeignKey(
        'solicitacoes.Solicitacao', on_delete=models.CASCADE, related_name='itens',
    )
    material = models.ForeignKey(
        'core.Material', on_delete=models.PROTECT, related_name='itens_solicitacao',
    )
    quantidade_solicitada = models.DecimalField(max_digits=14, decimal_places=3)
    quantidade_atendida = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    quantidade_devolvida = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDENTE)

    class Meta:
        db_table = 'item_solicitacao'
        constraints = [
            models.UniqueConstraint(
                fields=['solicitacao', 'material'], name='uq_item_solicitacao_material',
            ),
            models.CheckConstraint(
                check=models.Q(quantidade_solicitada__gt=0),
                name='ck_item_solicitacao_quantidade_solicitada_positiva',
            ),
            models.CheckConstraint(
                check=models.Q(quantidade_atendida__gte=0) & models.Q(quantidade_devolvida__gte=0),
                name='ck_item_solicitacao_quantidades_nao_negativas',
            ),
            models.CheckConstraint(
                check=models.Q(quantidade_atendida__lte=models.F('quantidade_solicitada')),
                name='ck_item_solicitacao_atendida_lte_solicitada',
            ),
            models.CheckConstraint(
                check=models.Q(quantidade_devolvida__lte=models.F('quantidade_atendida')),
                name='ck_item_solicitacao_devolvida_lte_atendida',
            ),
        ]

    def __str__(self):
        return f'{self.material.codigo} — {self.quantidade_solicitada} ({self.solicitacao.numero})'

    def saldo_pendente(self):
        return self.quantidade_solicitada - self.quantidade_atendida