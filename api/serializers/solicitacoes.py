from rest_framework import serializers

from solicitacoes.models import ItemSolicitacao, Solicitacao


class ItemSolicitacaoSerializer(serializers.ModelSerializer):
    material_codigo = serializers.CharField(source='material.codigo', read_only=True)
    saldo_pendente = serializers.SerializerMethodField()

    class Meta:
        model = ItemSolicitacao
        fields = [
            'id', 'solicitacao', 'material', 'material_codigo',
            'quantidade_solicitada', 'quantidade_atendida', 'quantidade_devolvida',
            'status', 'saldo_pendente',
        ]
        # campos derivados — nunca aceitos como input, só refletem o que
        # os services já gravaram
        read_only_fields = ['quantidade_atendida', 'quantidade_devolvida', 'status']

    def get_saldo_pendente(self, obj):
        return obj.saldo_pendente()


class ItemSolicitacaoCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemSolicitacao
        fields = ['material', 'quantidade_solicitada']

    def validate_quantidade_solicitada(self, quantidade):
        if quantidade <= 0:
            raise serializers.ValidationError('Quantidade solicitada deve ser maior que zero.')
        return quantidade


class SolicitacaoSerializer(serializers.ModelSerializer):
    itens = ItemSolicitacaoSerializer(many=True, read_only=True)
    solicitante_nome = serializers.CharField(source='solicitante.__str__', read_only=True)
    posto_nome = serializers.CharField(source='posto.nome', read_only=True)

    class Meta:
        model = Solicitacao
        fields = [
            'id', 'numero', 'status', 'data_solicitacao', 'data_prevista',
            'demanda', 'posto', 'posto_nome', 'solicitante', 'solicitante_nome',
            'observacao', 'itens',
        ]
        read_only_fields = ['status']  # status muda só via services


class SolicitacaoCreateSerializer(serializers.ModelSerializer):
    itens = ItemSolicitacaoCreateSerializer(many=True)

    class Meta:
        model = Solicitacao
        fields = ['numero', 'data_prevista', 'demanda', 'posto', 'observacao', 'itens']

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

        return itens

    def validate_data_prevista(self, data_prevista):
        from django.utils import timezone

        # ck_solicitacao_datas: data_prevista >= data_solicitacao.
        # data_solicitacao é sempre "agora" (definida em create() abaixo),
        # então comparamos contra o momento atual.
        if data_prevista < timezone.now():
            raise serializers.ValidationError(
                'Data prevista não pode ser anterior ao momento da solicitação.'
            )
        return data_prevista

    def create(self, validated_data):
        from django.utils import timezone

        itens_data = validated_data.pop('itens')
        solicitante = self.context['request'].user

        solicitacao = Solicitacao.objects.create(
            solicitante=solicitante,
            data_solicitacao=timezone.now(),
            **validated_data,
        )
        for item_data in itens_data:
            ItemSolicitacao.objects.create(solicitacao=solicitacao, **item_data)

        return solicitacao