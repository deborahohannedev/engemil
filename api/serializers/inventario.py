from rest_framework import serializers

from inventario.models import Inventario, ItemInventario, ParticipanteInventario


class ItemInventarioSerializer(serializers.ModelSerializer):
    material_codigo = serializers.CharField(source='material.codigo', read_only=True)
    material_descricao = serializers.CharField(source='material.descricao', read_only=True)
    unidade_sigla = serializers.CharField(source='material.unidade.sigla', read_only=True)
    foi_contado = serializers.SerializerMethodField()

    class Meta:
        model = ItemInventario
        fields = [
            'id', 'inventario', 'material', 'material_codigo', 'material_descricao', 'unidade_sigla',
            'saldo_sistema', 'quantidade_sistema', 'quantidade_fisica',
            'divergencia', 'ajuste', 'observacao', 'foi_contado',
        ]
        read_only_fields = ['saldo_sistema', 'quantidade_sistema', 'divergencia', 'ajuste']

    def get_foi_contado(self, obj):
        return obj.foi_contado()


class ParticipanteInventarioSerializer(serializers.ModelSerializer):
    usuario_nome = serializers.CharField(source='usuario.__str__', read_only=True)

    class Meta:
        model = ParticipanteInventario
        fields = ['id', 'inventario', 'usuario', 'usuario_nome', 'funcao']


class InventarioSerializer(serializers.ModelSerializer):
    itens = ItemInventarioSerializer(many=True, read_only=True)
    participantes = ParticipanteInventarioSerializer(many=True, read_only=True)
    encerrado_por_nome = serializers.SerializerMethodField()

    def get_encerrado_por_nome(self, obj):
        return str(obj.encerrado_por) if obj.encerrado_por else None

    class Meta:
        model = Inventario
        fields = [
            'id', 'data_inicio', 'data_fim', 'encerrado_em', 'encerrado_por',
            'encerrado_por_nome', 'situacao', 'observacao', 'itens', 'participantes',
        ]
        read_only_fields = ['data_fim', 'encerrado_em', 'encerrado_por', 'situacao']


class InventarioCreateSerializer(serializers.ModelSerializer):
    """
    Criação usa InventarioService.iniciar(observacao) na view — não é um
    create() de model simples. Não recebe lista de materiais: o service
    sempre inclui todos os materiais com situação ATIVO automaticamente.
    """

    class Meta:
        model = Inventario
        fields = ['observacao']