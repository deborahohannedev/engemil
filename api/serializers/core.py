from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from core.models import (
    Demanda, Fornecedor, Material, Movimentacao,
    Perfil, Posto, ReferenciaTecnica, UnidadeMedida, Usuario,
)
from core.validators import validar_quantidade_por_unidade


class PerfilSerializer(serializers.ModelSerializer):
    class Meta:
        model = Perfil
        fields = ['id', 'nome', 'funcao']


class PostoSerializer(serializers.ModelSerializer):
    responsavel_nome = serializers.SerializerMethodField()

    class Meta:
        model = Posto
        fields = ['id', 'codigo', 'nome', 'descricao', 'responsavel', 'responsavel_nome']

    def get_responsavel_nome(self, obj):
        return str(obj.responsavel) if obj.responsavel else None


class UsuarioSerializer(serializers.ModelSerializer):
    perfil_funcao = serializers.CharField(source='perfil.funcao', read_only=True)

    class Meta:
        model = Usuario
        fields = [
            'id', 'cpf', 'nome', 'sobrenome', 'email', 'telefone', 'ramal',
            'situacao', 'senha_temporaria', 'perfil', 'perfil_funcao', 'posto',
        ]
        read_only_fields = ['senha_temporaria']

class UsuarioCreateSerializer(serializers.ModelSerializer):
    senha_gerada = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = [
            'id', 'cpf', 'nome', 'sobrenome', 'email', 'telefone', 'ramal',
            'situacao', 'perfil', 'posto', 'senha_gerada',
        ]

    def get_senha_gerada(self, obj):
        return getattr(obj, '_senha_gerada', None)

    def create(self, validated_data):
        from core.models import gerar_senha_temporaria

        senha = gerar_senha_temporaria()
        usuario = Usuario.objects.create_user(password=senha, **validated_data)
        usuario._senha_gerada = senha  # atributo temporário, não persiste no banco
        return usuario

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
            'estoque_minimo', 'estoque_real', 'valor_unitario', 'situacao', 'referencia_tecnica',
        ]
        # estoque_real é mantido só pelo MovimentacaoService — nunca aceito
        # como input direto do usuário.
        read_only_fields = ['estoque_real']

    def validate(self, data):
        estoque_minimo = data.get('estoque_minimo', getattr(self.instance, 'estoque_minimo', None))
        valor_unitario = data.get('valor_unitario', getattr(self.instance, 'valor_unitario', None))
        unidade = data.get('unidade', getattr(self.instance, 'unidade', None))

        if estoque_minimo is not None and estoque_minimo < 0:
            raise serializers.ValidationError({
                'estoque_minimo': 'Estoque mínimo não pode ser negativo.'
            })

        if valor_unitario is not None and valor_unitario < 0:
            raise serializers.ValidationError({
                'valor_unitario': 'Valor unitário não pode ser negativo.'
            })

        if unidade is not None and estoque_minimo is not None:
            try:
                validar_quantidade_por_unidade(estoque_minimo, unidade)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({'estoque_minimo': exc.messages})

        return data


class MovimentacaoSerializer(serializers.ModelSerializer):
    """
    Somente leitura em toda a API — Movimentacao nunca é criada nem
    editada diretamente via endpoint. Toda criação passa pelos serviços
    de domínio (solicitacoes, entradas, devolucoes, inventario).
    """
    material_codigo = serializers.CharField(source='material.codigo', read_only=True)
    material_descricao = serializers.CharField(source='material.descricao', read_only=True)
    unidade_sigla = serializers.CharField(source='material.unidade.sigla', read_only=True)
    usuario_nome = serializers.CharField(source='usuario.__str__', read_only=True)

    class Meta:
        model = Movimentacao
        fields = [
            'id', 'material', 'material_codigo', 'material_descricao', 'unidade_sigla', 'solicitacao', 'entrada',
            'devolucao', 'item_inventario', 'usuario', 'usuario_nome', 'tipo',
            'quantidade_anterior', 'quantidade_posterior',
            'saldo_anterior', 'saldo_posterior', 'observacao', 'data_movimentacao',
        ]
        read_only_fields = fields

class TrocarSenhaSerializer(serializers.Serializer):
    senha_atual = serializers.CharField(write_only=True)
    nova_senha = serializers.CharField(write_only=True, min_length=8)

    def validate(self, data):
        usuario = self.context['request'].user
        if not usuario.check_password(data['senha_atual']):
            raise serializers.ValidationError({'senha_atual': 'Senha atual incorreta.'})
        return data

    def save(self, **kwargs):
        usuario = self.context['request'].user
        usuario.set_password(self.validated_data['nova_senha'])
        usuario.senha_temporaria = False
        usuario.save(update_fields=['password', 'senha_temporaria'])
        return usuario