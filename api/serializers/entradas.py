from rest_framework import serializers

from entradas.models import Entrada, ItemEntrada


class ItemEntradaSerializer(serializers.ModelSerializer):
    material_codigo = serializers.CharField(source='material.codigo', read_only=True)

    class Meta:
        model = ItemEntrada
        fields = ['id', 'entrada', 'material', 'material_codigo', 'quantidade', 'valor_unitario', 'valor_total']
        # valor_total é sempre calculado no save() do model — nunca aceito como input
        read_only_fields = ['valor_total']


class ItemEntradaCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemEntrada
        fields = ['material', 'quantidade', 'valor_unitario']

    def validate_quantidade(self, quantidade):
        if quantidade <= 0:
            raise serializers.ValidationError('Quantidade deve ser maior que zero.')
        return quantidade

    def validate_valor_unitario(self, valor_unitario):
        if valor_unitario < 0:
            raise serializers.ValidationError('Valor unitário não pode ser negativo.')
        return valor_unitario


class EntradaSerializer(serializers.ModelSerializer):
    itens = ItemEntradaSerializer(many=True, read_only=True)
    fornecedor_nome = serializers.CharField(source='fornecedor.nome', read_only=True, default=None)
    responsavel_nome = serializers.CharField(source='responsavel.__str__', read_only=True)

    class Meta:
        model = Entrada
        fields = [
            'id', 'fornecedor', 'fornecedor_nome', 'responsavel', 'responsavel_nome',
            'nota_fiscal', 'data_entrada', 'confirmada_em', 'itens',
        ]
        read_only_fields = ['confirmada_em']

class EntradaCreateSerializer(serializers.ModelSerializer):
    """'responsavel' vem do usuário autenticado, não é campo de entrada."""
    itens = ItemEntradaCreateSerializer(many=True)

    class Meta:
        model = Entrada
        fields = ['fornecedor', 'nota_fiscal', 'data_entrada', 'itens']

    def validate_itens(self, itens):
        if not itens:
            raise serializers.ValidationError('Entrada deve ter pelo menos um item.')
        return itens

    def create(self, validated_data):
        itens_data = validated_data.pop('itens')
        responsavel = self.context['request'].user

        entrada = Entrada.objects.create(responsavel=responsavel, **validated_data)
        for item_data in itens_data:
            ItemEntrada.objects.create(entrada=entrada, **item_data)

        return entrada