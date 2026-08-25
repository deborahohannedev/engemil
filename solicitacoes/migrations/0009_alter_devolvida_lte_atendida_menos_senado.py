from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('solicitacoes', '0008_itemsolicitacao_quantidade_separada_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='itemsolicitacao',
            name='ck_item_solicitacao_devolvida_lte_atendida',
        ),
        migrations.AddConstraint(
            model_name='itemsolicitacao',
            constraint=models.CheckConstraint(
                check=models.Q(
                    ('quantidade_devolvida__lte', models.F('quantidade_atendida') - models.F('quantidade_saida_senado'))
                ),
                name='ck_item_solicitacao_devolvida_lte_atendida_menos_senado',
            ),
        ),
    ]
