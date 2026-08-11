import uuid

from django.db import models


class Inventario(models.Model):
    """
    'encerrado_em' e 'encerrado_por' só são preenchidos quando
    situacao=ENCERRADO — garantido pelo CheckConstraint abaixo.
    """

    class Situacao(models.TextChoices):
        # todo: verificar se os status estão corretos, pois o front está usando outros nomes
        EM_ANDAMENTO = 'EM_ANDAMENTO', 'Em andamento'
        ENCERRADO = 'ENCERRADO', 'Encerrado'
        CANCELADO = 'CANCELADO', 'Cancelado'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    data_inicio = models.DateTimeField()
    data_fim = models.DateTimeField(null=True, blank=True)
    encerrado_em = models.DateTimeField(null=True, blank=True)
    encerrado_por = models.ForeignKey(
        'core.Usuario', on_delete=models.PROTECT, related_name='inventarios_encerrados',
        null=True, blank=True,
    )
    situacao = models.CharField(
        max_length=20, choices=Situacao.choices, default=Situacao.EM_ANDAMENTO,
    )
    observacao = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'inventario'
        ordering = ['-data_inicio']
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(situacao='ENCERRADO', encerrado_em__isnull=False, encerrado_por__isnull=False)
                    | ~models.Q(situacao='ENCERRADO')
                ),
                name='ck_inventario_encerramento',
            ),
        ]

    def __str__(self):
        return f'Inventário {self.data_inicio:%d/%m/%Y}'


class ParticipanteInventario(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    inventario = models.ForeignKey(
        'inventario.Inventario', on_delete=models.CASCADE, related_name='participantes',
    )
    usuario = models.ForeignKey(
        'core.Usuario', on_delete=models.PROTECT, related_name='participacoes_inventario',
    )
    funcao = models.CharField(max_length=50)

    class Meta:
        db_table = 'participante_inventario'
        constraints = [
            models.UniqueConstraint(
                fields=['inventario', 'usuario'], name='uq_participante_inventario',
            ),
        ]

    def __str__(self):
        return f'{self.usuario} ({self.funcao})'


class ItemInventario(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    inventario = models.ForeignKey(
        'inventario.Inventario', on_delete=models.CASCADE, related_name='itens',
    )
    material = models.ForeignKey(
        'core.Material', on_delete=models.PROTECT, related_name='itens_inventario',
    )

    # 'saldo_sistema' é o valor em R$ registrado no sistema no momento da
    # contagem; 'quantidade_sistema' é a quantidade física registrada —
    # mesma distinção quantidade/saldo aplicada em Movimentacao.
    saldo_sistema = models.DecimalField(max_digits=14, decimal_places=2)
    quantidade_sistema = models.DecimalField(max_digits=14, decimal_places=3)

    quantidade_fisica = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True,
        help_text='Preenchida durante a contagem física. NULL = ainda não contado.',
    )
    divergencia = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    ajuste = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    observacao = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'item_inventario'
        constraints = [
            models.UniqueConstraint(
                fields=['inventario', 'material'], name='uq_item_inventario_material',
            ),
        ]

    def __str__(self):
        return f'{self.material.codigo} — inv. {self.inventario_id}'

    def foi_contado(self) -> bool:
        return self.quantidade_fisica is not None
    def calcular_divergencia(self):
        if not self.foi_contado():
            return None
        # todo: explicar que a divergencia é calculada como quantidade_fisica - quantidade_sistema
        self.divergencia = self.quantidade_fisica - self.quantidade_sistema
        return self.divergencia