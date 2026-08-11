from rest_framework import serializers

from core.models import (
    Demanda, Fornecedor, Material, Movimentacao,
    Perfil, Posto, ReferenciaTecnica, UnidadeMedida, Usuario,
)


class PerfilSerializer(serializers.ModelSerializer):
    class Meta:
        model = Perfil
        fields = ['id', 'nome', 'funcao']


class PostoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Posto
        fields = ['id', 'codigo', 'nome', 'descricao', 'responsavel']


class UsuarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = [
            'id', 'nome', 'sobrenome', 'email', 'telefone', 'ramal',
            'situacao', 'perfil', 'posto',
        ]


class UnidadeMedidaSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnidadeMedida
        fields = ['id', 'sigla', 'descricao']


class ReferenciaTecnicaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferenciaTecnica
        fields = ['id', 'codigo', 'nome', 'descricao']


class FornecedorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Fornecedor
        fields = ['id', 'nome', 'cnpj', 'telefone', 'email', 'nome_vendedor']


class DemandaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Demanda
        fields = ['id', 'numero', 'descricao', 'origem', 'prazo', 'situacao']


class MaterialSerializer(serializers.ModelSerializer):
    unidade_sigla = serializers.CharField(source='unidade.sigla', read_only=True)

    class Meta:
        model = Material
        fields = [
            'id', 'codigo', 'descricao', 'fabricante', 'unidade', 'unidade_sigla',
            'estoque_minimo', 'estoque_ideal', 'situacao', 'referencia_tecnica',
        ]

    def validate(self, data):
        estoque_minimo = data.get('estoque_minimo', getattr(self.instance, 'estoque_minimo', None))
        estoque_ideal = data.get('estoque_ideal', getattr(self.instance, 'estoque_ideal', None))

        if estoque_minimo is not None and estoque_minimo < 0:
            raise serializers.ValidationError({
                'estoque_minimo': 'Estoque mínimo não pode ser negativo.'
            })

        if estoque_minimo is not None and estoque_ideal is not None and estoque_ideal < estoque_minimo:
            raise serializers.ValidationError({
                'estoque_ideal': 'Estoque ideal deve ser maior ou igual ao estoque mínimo.'
            })
        return data


class MovimentacaoSerializer(serializers.ModelSerializer):
    """
    Somente leitura em toda a API — Movimentacao nunca é criada nem
    editada diretamente via endpoint. Toda criação passa pelos serviços
    de domínio (solicitacoes, entradas, devolucoes, inventario).
    """
    material_codigo = serializers.CharField(source='material.codigo', read_only=True)

    class Meta:
        model = Movimentacao
        fields = [
            'id', 'material', 'material_codigo', 'solicitacao', 'entrada',
            'devolucao', 'item_inventario', 'usuario', 'tipo',
            'quantidade_anterior', 'quantidade_posterior',
            'saldo_anterior', 'saldo_posterior', 'observacao', 'data_movimentacao',
        ]
        read_only_fields = fields