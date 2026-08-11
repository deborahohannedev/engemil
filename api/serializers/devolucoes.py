from rest_framework import serializers

from devolucoes.models import Devolucao


class DevolucaoSerializer(serializers.ModelSerializer):
    material_codigo = serializers.CharField(
        source='item_solicitacao.material.codigo', read_only=True,
    )
    esta_pendente = serializers.SerializerMethodField()

    class Meta:
        model = Devolucao
        fields = [
            'id', 'item_solicitacao', 'material_codigo', 'responsavel_conferencia',
            'quantidade', 'condicao', 'decisao', 'observacao',
            'data_inicial', 'data_final', 'esta_pendente',
        ]
        # decisao/data_final só mudam via DevolucaoService.aprovar()/rejeitar()
        read_only_fields = ['decisao', 'data_final']

    def get_esta_pendente(self, obj):
        return obj.esta_pendente()


class DevolucaoCreateSerializer(serializers.ModelSerializer):
    """
    'responsavel_conferencia' e 'data_inicial' vêm da view (usuário
    autenticado + timestamp), não são campos de entrada.
    """
    class Meta:
        model = Devolucao
        fields = ['item_solicitacao', 'quantidade', 'condicao', 'observacao']

    def validate_quantidade(self, quantidade):
        if quantidade <= 0:
            raise serializers.ValidationError('Quantidade devolvida deve ser maior que zero.')
        return quantidade