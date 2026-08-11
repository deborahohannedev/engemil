import uuid

from django.db import models


class Entrada(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fornecedor = models.ForeignKey(
        'core.Fornecedor', on_delete=models.PROTECT, related_name='entradas',
        null=True, blank=True,
    )
    responsavel = models.ForeignKey(
        'core.Usuario', on_delete=models.PROTECT, related_name='entradas_registradas',
    )
    nota_fiscal = models.CharField(max_length=50, null=True, blank=True)
    data_entrada = models.DateTimeField()

    class Meta:
        db_table = 'entrada'
        ordering = ['-data_entrada']

    def __str__(self):
        referencia = self.nota_fiscal or str(self.id)[:8]
        return f'Entrada {referencia}'


class ItemEntrada(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entrada = models.ForeignKey(
        'entradas.Entrada', on_delete=models.CASCADE, related_name='itens',
    )
    material = models.ForeignKey(
        'core.Material', on_delete=models.PROTECT, related_name='itens_entrada',
    )
    quantidade = models.DecimalField(max_digits=14, decimal_places=3)
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=2)
    valor_total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        db_table = 'item_entrada'
        constraints = [
            models.CheckConstraint(
                check=models.Q(quantidade__gt=0),
                name='ck_item_entrada_quantidade_positiva',
            ),
            models.CheckConstraint(
                check=models.Q(valor_unitario__gte=0) & models.Q(valor_total__gte=0),
                name='ck_item_entrada_valores_nao_negativos',
            ),
        ]

    def __str__(self):
        return f'{self.material.codigo} — {self.quantidade} un.'

    def save(self, *args, **kwargs):
        # todo: explicar que valor_total é sempre derivado — nunca confiar em valor enviado pelo cliente da API para esse campo
        # valor_total é sempre derivado — nunca confiar em valor enviado
        # pelo cliente da API para esse campo
        self.valor_total = self.quantidade * self.valor_unitario
        super().save(*args, **kwargs)