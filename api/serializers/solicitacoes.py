from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from core.validators import validar_quantidade_por_unidade
from solicitacoes.domain.services import SolicitacaoService
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


class ItemSolicitacaoEditSerializer(serializers.ModelSerializer):
    """
    'id' presente = item já existente sendo alterado (ou mantido igual);
    'id' ausente = item novo, criado igual ao fluxo de criação. Todo item
    existente que NÃO aparecer na lista enviada é entendido como removido
    pelo usuário — ver SolicitacaoEditSerializer.update().
    """
    id = serializers.UUIDField(required=False)
    observacao = serializers.CharField(required=True, allow_blank=False)

    class Meta:
        model = ItemSolicitacao
        fields = ['id', 'material', 'quantidade_solicitada', 'observacao']

    def validate_quantidade_solicitada(self, quantidade):
        if quantidade <= 0:
            raise serializers.ValidationError('Quantidade solicitada deve ser maior que zero.')
        return quantidade


class SolicitacaoEditSerializer(serializers.ModelSerializer):
    """
    Serializer de edição — usado só pelas actions update/partial_update
    da view (PATCH/PUT em /solicitacoes/<id>/). Só é permitido editar uma
    Solicitacao com status ABERTA, EM_ANDAMENTO ou PARCIALMENTE_ATENDIDA
    (RN combinada com o cliente — ver AskUserQuestion desta sessão).

    'numero' fica de fora de propósito — não faz parte do fluxo de
    edição, só cabeçalho (demanda/posto/observação) + itens.

    Item já com quantidade_atendida > 0 (parcial ou totalmente atendido)
    não pode trocar de material nem ter a quantidade reduzida abaixo do
    que já saiu do estoque, e não pode ser removido — o que já saiu não
    tem como "desacontecer" por aqui (RN-006/007, Movimentacao é
    append-only). Aumentar a quantidade de um item já ATENDIDO é
    permitido: reabre o item pra mais atendimento (mesma regra de status
    que confirmar_saida usa).
    """
    itens = ItemSolicitacaoEditSerializer(many=True)

    class Meta:
        model = Solicitacao
        fields = ['demanda', 'posto', 'observacao', 'itens']

    def validate(self, dados):
        solicitacao = self.instance
        editaveis = (
            Solicitacao.Status.ABERTA,
            Solicitacao.Status.EM_ANDAMENTO,
            Solicitacao.Status.PARCIALMENTE_ATENDIDA,
        )
        if solicitacao.status not in editaveis:
            raise serializers.ValidationError(
                f'Solicitação com status "{solicitacao.get_status_display()}" não pode ser editada.'
            )
        return dados

    def validate_itens(self, itens):
        if not itens:
            raise serializers.ValidationError('Solicitação deve ter pelo menos um item (RN-002).')

        itens_atuais = {item.id: item for item in self.instance.itens.all()}
        materiais_vistos = set()

        for item_data in itens:
            item_id = item_data.get('id')
            material = item_data['material']

            if item_id is not None:
                item_atual = itens_atuais.get(item_id)
                if item_atual is None:
                    raise serializers.ValidationError('Item não pertence a esta solicitação.')

                if item_atual.quantidade_atendida > 0:
                    if material.id != item_atual.material_id:
                        raise serializers.ValidationError(
                            f'Item {item_atual.material.codigo} já teve saída registrada — '
                            f'não é possível trocar o material.'
                        )
                    if item_data['quantidade_solicitada'] < item_atual.quantidade_atendida:
                        raise serializers.ValidationError(
                            f'Item {item_atual.material.codigo}: quantidade não pode ficar menor '
                            f'que {item_atual.quantidade_atendida}, já atendida.'
                        )

            if material.id in materiais_vistos:
                raise serializers.ValidationError(
                    f'Material {material.codigo} aparece mais de uma vez na solicitação.'
                )
            materiais_vistos.add(material.id)

            try:
                validar_quantidade_por_unidade(item_data['quantidade_solicitada'], material.unidade)
            except DjangoValidationError as exc:
                raise serializers.ValidationError(exc.messages)

        ids_no_payload = {i['id'] for i in itens if i.get('id') is not None}
        for item_id, item_atual in itens_atuais.items():
            if item_id not in ids_no_payload and item_atual.quantidade_atendida > 0:
                raise serializers.ValidationError(
                    f'Item {item_atual.material.codigo} já teve saída registrada e não pode ser removido.'
                )

        return itens

    def update(self, solicitacao, validated_data):
        itens_data = validated_data.pop('itens')

        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(solicitacao, attr, value)
            solicitacao.save()

            itens_atuais = {item.id: item for item in solicitacao.itens.all()}
            ids_no_payload = set()

            for item_data in itens_data:
                item_id = item_data.pop('id', None)
                if item_id is not None:
                    ids_no_payload.add(item_id)
                    item_atual = itens_atuais[item_id]
                    item_atual.material = item_data['material']
                    item_atual.quantidade_solicitada = item_data['quantidade_solicitada']
                    item_atual.observacao = item_data['observacao']
                    # mesma regra de status que confirmar_saida usa — aumentar
                    # a quantidade de um item ATENDIDO o reabre pra DISPONIVEL.
                    if item_atual.quantidade_atendida <= 0:
                        item_atual.status = ItemSolicitacao.Status.PENDENTE
                    elif item_atual.quantidade_atendida >= item_atual.quantidade_solicitada:
                        item_atual.status = ItemSolicitacao.Status.ATENDIDO
                    else:
                        item_atual.status = ItemSolicitacao.Status.DISPONIVEL
                    item_atual.save(update_fields=['material', 'quantidade_solicitada', 'observacao', 'status'])
                else:
                    ItemSolicitacao.objects.create(solicitacao=solicitacao, **item_data)

            for item_id, item_atual in itens_atuais.items():
                if item_id not in ids_no_payload:
                    item_atual.delete()

            SolicitacaoService().reconciliar_status_apos_edicao(solicitacao)

        solicitacao.refresh_from_db()
        return solicitacao