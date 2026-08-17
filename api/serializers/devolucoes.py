from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from api.permissions import Funcao
from core.validators import validar_quantidade_por_unidade
from devolucoes.models import Devolucao


class DevolucaoSerializer(serializers.ModelSerializer):
    material_codigo = serializers.CharField(
        source='item_solicitacao.material.codigo', read_only=True,
    )
    material_descricao = serializers.CharField(
        source='item_solicitacao.material.descricao', read_only=True,
    )
    unidade_sigla = serializers.CharField(
        source='item_solicitacao.material.unidade.sigla', read_only=True,
    )
    responsavel_conferencia_nome = serializers.CharField(
        source='responsavel_conferencia.__str__', read_only=True,
    )
    esta_pendente = serializers.SerializerMethodField()

    class Meta:
        model = Devolucao
        fields = [
            'id', 'item_solicitacao', 'material_codigo', 'material_descricao', 'unidade_sigla',
            'responsavel_conferencia', 'responsavel_conferencia_nome',
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

    def validate(self, data):
        usuario = self.context['request'].user
        item_solicitacao = data['item_solicitacao']

        if usuario.perfil.funcao == Funcao.ENCARREGADO:
            if item_solicitacao.solicitacao.solicitante_id != usuario.id:
                raise serializers.ValidationError(
                    'Você só pode informar devolução de itens de solicitações que você criou.'
                )

        # só pode existir uma devolução em aberto por item — a próxima só
        # pode ser aberta depois que a anterior for aprovada ou rejeitada.
        if item_solicitacao.devolucoes.filter(data_final__isnull=True).exists():
            raise serializers.ValidationError(
                'Este item já tem uma devolução pendente. Aguarde ela ser aprovada '
                'ou rejeitada antes de abrir outra.'
            )

        # quantidade disponível é sempre recalculada aqui, na hora do
        # submit — nunca confia em um valor vindo do cliente, que pode
        # estar desatualizado.
        disponivel = item_solicitacao.quantidade_atendida - item_solicitacao.quantidade_devolvida
        if data['quantidade'] > disponivel:
            raise serializers.ValidationError({
                'quantidade': f'Quantidade devolvida não pode passar de {disponivel} (disponível pra devolução).'
            })

        try:
            validar_quantidade_por_unidade(data['quantidade'], item_solicitacao.material.unidade)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'quantidade': exc.messages})

        return data