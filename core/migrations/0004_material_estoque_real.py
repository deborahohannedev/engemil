from decimal import Decimal

from django.db import migrations, models


def recalcular_estoque_real(apps, schema_editor):
    Material = apps.get_model('core', 'Material')
    Movimentacao = apps.get_model('core', 'Movimentacao')

    for material in Material.objects.all():
        ultima = (
            Movimentacao.objects
            .filter(material=material)
            .order_by('-data_movimentacao')
            .first()
        )
        material.estoque_real = ultima.quantidade_posterior if ultima else Decimal('0')
        material.save(update_fields=['estoque_real'])


def reverter_estoque_real(apps, schema_editor):
    # não há como recuperar o antigo "estoque_ideal" — vira 0.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_usuario_senha_temporaria'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='material',
            name='ck_material_estoque_ideal',
        ),
        migrations.RenameField(
            model_name='material',
            old_name='estoque_ideal',
            new_name='estoque_real',
        ),
        migrations.AlterField(
            model_name='material',
            name='estoque_real',
            field=models.DecimalField(max_digits=14, decimal_places=3, default=Decimal('0')),
        ),
        migrations.RunPython(recalcular_estoque_real, reverter_estoque_real),
    ]
