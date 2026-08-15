from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from core.validators import validar_quantidade_por_unidade
from solicitacoes.models import ItemSolicitacao, Solicitacao


class ItemSolicitacaoSerializer(serializers.ModelSerializer):
    material_codigo = serializers.CharField(source='material.codigo', read_only=True)
    material_descricao = serializers.CharField(source='material.descricao', read_only=True)
    unidade_sigla = serializers.CharField(source='material.unidade.sigla', read_only=True)
    # valor unitário sempre lido do cadastro do Material — não é um snapshot
    # gravado no item, então reflete o preço cadastral atual do material.
    material_valor_unitario = serializers.DecimalField(
        source='material.valor_unitario', max_digits=14, decimal_places=2, read_only=True,
    )
    valor_total = serializers.SerializerMethodField()
    saldo_pendente = serializers.SerializerMethodField()
    tem_devolucao_pendente = serializers.SerializerMethodField()

    class Meta:
        model = ItemSolicitacao
        fields = [
            'id', 'solicitacao', 'material', 'material_codigo', 'material_descricao', 'unidade_sigla',
            'material_valor_unitario', 'valor_total',
            'quantidade_solicitada', 'quantidade_atendida', 'quantidade_devolvida',
            'status', 'saldo_pendente', 'observacao', 'tem_devolucao_pendente',
        ]
        # campos derivados — nunca aceitos como input, só refletem o que
        # os services já gravaram
        read_only_fields = ['quantidade_atendida', 'quantidade_devolvida', 'status']

    def get_saldo_pendente(self, obj):
        return obj.saldo_pendente()

    def get_valor_total(self, obj):
        if obj.material.valor_unitario is None:
            return None
        return obj.quantidade_solicitada * obj.material.valor_unitario

    def get_tem_devolucao_pendente(self, obj):
        return obj.devolucoes.filter(data_final__isnull=True).exists()


class ItemSolicitacaoCreateSerializer(serializers.ModelSerializer):
    # obrigatória só na criação — o campo no model continua null=True pra
    # não travar registros antigos/outros caminhos de escrita.
    observacao = serializers.CharField(required=True, allow_blank=False)

    class Meta:
        model = ItemSolicitacao
        fields = ['material', 'quantidade_solicitada', 'observacao']

    def validate_quantidade_solicitada(self, quantidade):
        if quantidade <= 0:
            raise serializers.ValidationError('Quantidade solicitada deve ser maior que zero.')
        return quantidade


class SolicitacaoSerializer(serializers.ModelSerializer):
    itens = ItemSolicitacaoSerializer(many=True, read_only=True)
    solicitante_nome = serializers.CharField(source='solicitante.__str__', read_only=True)
    posto_nome = serializers.CharField(source='posto.nome', read_only=True)
    valor_total = serializers.SerializerMethodField()

    class Meta:
        model = Solicitacao
        fields = [
            'id', 'numero', 'status', 'data_solicitacao', 'data_prevista',
            'demanda', 'posto', 'posto_nome', 'solicitante', 'solicitante_nome',
            'observacao', 'itens', 'valor_total', 'reaberta_em',
        ]
        read_only_fields = ['status', 'reaberta_em']  # mudam só via services

    def get_valor_total(self, obj):
        # soma só os itens cujo material tem valor_unitario cadastrado —
        # itens sem preço não entram na soma (não tem como estimar).
        total = sum(
            (item.quantidade_solicitada * item.material.valor_unitario
             for item in obj.itens.all() if item.material.valor_unitario is not None),
            Decimal('0'),
        )
        return total


class SolicitacaoCreateSerializer(serializers.ModelSerializer):
    itens = ItemSolicitacaoCreateSerializer(many=True)

    class Meta:
        model = Solicitacao
        fields = ['numero', 'demanda', 'posto', 'observacao', 'itens']

    def validate_itens(self, itens):
        if not itens:
            raise serializers.ValidationError(
                'Solicitação deve ter pelo menos um item (RN-002).'
            )

        # ck_material_solicitacao: material não pode repetir na mesma solicitação
        materiais_vistos = set()
        for item in itens:
            material = item['material']
            if material.id in materiais_vistos:
                raise serializers.ValidationError(
                    f'Material {material.codigo} aparece mais de uma vez na solicitação.'
                )
            materiais_vistos.add(material.id)

            try:
                validar_quantidade_por_unidade(item['quantidade_solicitada'], material.unidade)
            except DjangoValidationError as exc:
                raise serializers.ValidationError(exc.messages)

        return itens

    def create(self, validated_data):
        from django.utils import timezone

        itens_data = validated_data.pop('itens')
        solicitante = self.context['request'].user
        agora = timezone.now()

        # data_prevista não é mais input do usuário — nasce igual à
        # data_solicitacao (RN antiga de "data prevista futura" foi
        # descartada a pedido do cliente).
        solicitacao = Solicitacao.objects.create(
            solicitante=solicitante,
            data_solicitacao=agora,
            data_prevista=agora,
            **validated_data,
        )
        for item_data in itens_data:
            ItemSolicitacao.objects.create(solicitacao=solicitacao, **item_data)

        return solicitacao