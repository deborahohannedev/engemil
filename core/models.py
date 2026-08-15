import uuid
import secrets
import string
from decimal import Decimal

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models

from core.validators import validar_cpf, validar_telefone


class Perfil(models.Model):
    """
    Perfil de acesso (ex: Almoxarife, Solicitante, Administrador).
    'funcao' é a chave de negócio única usada em regras de permissão
    no código; 'nome' é só rótulo de exibição, não é único.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nome = models.CharField(max_length=100)
    funcao = models.CharField(max_length=50, unique=True)

    class Meta:
        db_table = 'perfil'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Posto(models.Model):
    """
    Posto/unidade de trabalho. 'responsavel' é opcional (posto pode
    existir sem responsável definido, vinculado depois) e é uma relação
    DISTINTA de Usuario.posto (lotação).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    codigo = models.CharField(max_length=30, unique=True)
    nome = models.CharField(max_length=150)
    descricao = models.TextField(null=True, blank=True)
    responsavel = models.ForeignKey(
        'core.Usuario', on_delete=models.SET_NULL, related_name='postos_sob_responsabilidade',
        null=True, blank=True,
    )

    class Meta:
        db_table = 'posto'
        ordering = ['nome']

    def __str__(self):
        return f'{self.codigo} — {self.nome}'


def gerar_senha_temporaria(tamanho: int = 12) -> str:
    """
    Gera uma senha aleatória segura, usada como senha inicial de novos
    usuários — a pessoa é obrigada a trocar no primeiro acesso.
    """
    alfabeto = string.ascii_letters + string.digits + '!@#$%&*'
    return ''.join(secrets.choice(alfabeto) for _ in range(tamanho))

class UsuarioManager(BaseUserManager):
    """
    Manager customizado — login por CPF, não por e-mail.
    """

    def create_user(self, cpf, nome, sobrenome, email, password=None, **extra_fields):
        if not cpf:
            raise ValueError('O CPF é obrigatório para criar um usuário.')
        if not email:
            raise ValueError('O e-mail é obrigatório para criar um usuário.')

        email = self.normalize_email(email)
        extra_fields.setdefault('situacao', Usuario.Situacao.ATIVO)
        usuario = self.model(cpf=cpf, nome=nome, sobrenome=sobrenome, email=email, **extra_fields)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_superuser(self, cpf, nome, sobrenome, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('situacao', Usuario.Situacao.ATIVO)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superusuário precisa ter is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superusuário precisa ter is_superuser=True.')

        return self.create_user(cpf, nome, sobrenome, email, password, **extra_fields)


class Usuario(AbstractBaseUser, PermissionsMixin):
    """
    Usuário do sistema Engemil. Substitui o User padrão do Django
    (AUTH_USER_MODEL em settings).

    'is_staff' controla acesso ao Django Admin (uso interno/técnico,
    não é o mesmo que perfil de negócio). 'is_active' é derivado de
    'situacao', não duplicado.
    """

    class Situacao(models.TextChoices):
        # todo: verificar se os status estão corretos, pois o front está usando outros nomes
        ATIVO = 'ATIVO', 'Ativo'
        INATIVO = 'INATIVO', 'Inativo'
        AFASTADO = 'AFASTADO', 'Afastado'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nome = models.CharField(max_length=100)
    sobrenome = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    telefone = models.CharField(max_length=20, null=True, blank=True, validators=[validar_telefone])
    ramal = models.CharField(max_length=10, null=True, blank=True)
    situacao = models.CharField(max_length=20, choices=Situacao.choices, default=Situacao.ATIVO)
    senha_temporaria = models.BooleanField(
        default=True,
        help_text='True enquanto o usuário não trocou a senha inicial gerada pelo sistema.',
    )
    cpf = models.CharField(max_length=14, unique=True, validators=[validar_cpf])

    # todo: verificar se os status estão corretos, pois o front está usando outros nomes
    perfil = models.ForeignKey(
        'core.Perfil', on_delete=models.PROTECT, related_name='usuarios',
    )
    posto = models.ForeignKey(
        'core.Posto', on_delete=models.SET_NULL, related_name='usuarios_lotados',
        null=True, blank=True,
        help_text='Posto de lotação. Opcional — não confundir com Posto.responsavel.',
    )

    is_staff = models.BooleanField(
        default=False, help_text='Acesso ao Django Admin. Independente do perfil de negócio.',
    )

    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UsuarioManager()

    USERNAME_FIELD = 'cpf'
    REQUIRED_FIELDS = ['nome', 'sobrenome', 'email']

    class Meta:
        db_table = 'usuario'
        ordering = ['nome', 'sobrenome']

    def __str__(self):
        return f'{self.nome} {self.sobrenome}'

    @property
    def is_active(self):
        return self.situacao == self.Situacao.ATIVO

    @is_active.setter
    def is_active(self, value):
        # Necessário pois Django internamente tenta setar is_active em
        # alguns fluxos (ex: testes, alguns backends). Traduzimos de volta
        # para 'situacao' em vez de aceitar um campo booleano paralelo.
        self.situacao = self.Situacao.ATIVO if value else self.Situacao.INATIVO

    def save(self, *args, **kwargs):
        if self.cpf:
            self.cpf = ''.join(filter(str.isdigit, self.cpf))
        super().save(*args, **kwargs)


class UnidadeMedida(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sigla = models.CharField(max_length=10, unique=True)
    descricao = models.CharField(max_length=100)

    class Meta:
        db_table = 'unidade_medida'
        verbose_name = 'Unidade de Medida'
        verbose_name_plural = 'Unidades de Medida'
        ordering = ['sigla']

    def __str__(self):
        return self.sigla


class ReferenciaTecnica(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    codigo = models.CharField(max_length=50, unique=True)
    nome = models.CharField(max_length=150)
    descricao = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        db_table = 'referencia_tecnica'
        verbose_name = 'Referência Técnica'
        verbose_name_plural = 'Referências Técnicas'
        ordering = ['codigo']

    def __str__(self):
        return f'{self.codigo} — {self.nome}'


class Fornecedor(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nome = models.CharField(max_length=200)
    cnpj = models.CharField(max_length=18, unique=True)
    telefone = models.CharField(max_length=20, null=True, blank=True, validators=[validar_telefone])
    email = models.EmailField(null=True, blank=True)
    nome_vendedor = models.CharField(max_length=150, null=True, blank=True)

    class Meta:
        db_table = 'fornecedor'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Demanda(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    numero = models.CharField(max_length=30, unique=True)
    descricao = models.CharField(max_length=300)
    origem = models.CharField(max_length=50)
    prazo = models.DateField(null=True, blank=True)
    situacao = models.CharField(max_length=20)

    class Meta:
        db_table = 'demanda'
        ordering = ['-numero']

    def __str__(self):
        return self.numero


class Material(models.Model):
    """
    'descricao' é o único campo que nomeia o item (não existe campo
    'nome' separado) — por isso é obrigatório, diferente dos demais
    campos 'descricao' do sistema, que são opcionais.
    """

    class Situacao(models.TextChoices):
        # todo: verificar se os status estão corretos, pois o front está usando outros nomes
        ATIVO = 'ATIVO', 'Ativo'
        INATIVO = 'INATIVO', 'Inativo'
        DESCONTINUADO = 'DESCONTINUADO', 'Descontinuado'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    codigo = models.CharField(max_length=50, unique=True)
    descricao = models.CharField(max_length=300)
    fabricante = models.CharField(max_length=150, null=True, blank=True)
    unidade = models.ForeignKey(
        'core.UnidadeMedida', on_delete=models.PROTECT, related_name='materiais',
    )
    estoque_minimo = models.DecimalField(max_digits=14, decimal_places=3)
    estoque_ideal = models.DecimalField(max_digits=14, decimal_places=3)
    situacao = models.CharField(max_length=20, choices=Situacao.choices, default=Situacao.ATIVO)
    referencia_tecnica = models.ForeignKey(
        'core.ReferenciaTecnica', on_delete=models.SET_NULL, related_name='materiais',
        null=True, blank=True,
    )

    class Meta:
        db_table = 'material'
        ordering = ['codigo']
        constraints = [
            models.CheckConstraint(
                check=models.Q(estoque_minimo__gte=0),
                name='ck_material_estoque_minimo',
            ),
            models.CheckConstraint(
                check=models.Q(estoque_ideal__gte=models.F('estoque_minimo')),
                name='ck_material_estoque_ideal',
            ),
        ]

    def __str__(self):
        return f'{self.codigo} — {self.descricao}'


class Movimentacao(models.Model):
    """
    Tabela-fato de auditoria central do sistema. Todo movimento de saldo
    de estoque passa por aqui. Registro append-only — não deve existir
    fluxo de update/delete sobre movimentações já criadas.

    Exatamente UMA das 4 FKs de origem deve estar preenchida por registro.
    Validado em duas camadas: aqui no banco (CheckConstraint abaixo) e
    também na aplicação (Value Object OrigemMovimentacao, que veremos
    a seguir em core/domain/).

    Nunca crie uma Movimentacao diretamente fora do MovimentacaoService.
    """

    class Tipo(models.TextChoices):
        ENTRADA = 'ENTRADA', 'Entrada'
        SAIDA = 'SAIDA', 'Saída'
        DEVOLUCAO = 'DEVOLUCAO', 'Devolução'
        AJUSTE_INVENTARIO = 'AJUSTE_INVENTARIO', 'Ajuste de Inventário'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    material = models.ForeignKey(
        'core.Material', on_delete=models.PROTECT, related_name='movimentacoes',
    )

    solicitacao = models.ForeignKey(
        'solicitacoes.Solicitacao', on_delete=models.PROTECT, related_name='movimentacoes',
        null=True, blank=True,
    )
    entrada = models.ForeignKey(
        'entradas.Entrada', on_delete=models.PROTECT, related_name='movimentacoes',
        null=True, blank=True,
    )
    devolucao = models.ForeignKey(
        'devolucoes.Devolucao', on_delete=models.PROTECT, related_name='movimentacoes',
        null=True, blank=True,
    )
    item_inventario = models.ForeignKey(
        'inventario.ItemInventario', on_delete=models.PROTECT, related_name='movimentacoes',
        null=True, blank=True,
    )

    usuario = models.ForeignKey(
        'core.Usuario', on_delete=models.PROTECT, related_name='movimentacoes_realizadas',
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices)

    quantidade_anterior = models.DecimalField(max_digits=14, decimal_places=3)
    quantidade_posterior = models.DecimalField(max_digits=14, decimal_places=3)
    saldo_anterior = models.DecimalField(max_digits=14, decimal_places=3)
    saldo_posterior = models.DecimalField(max_digits=14, decimal_places=3)

    observacao = models.TextField(null=True, blank=True)
    data_movimentacao = models.DateTimeField()

    class Meta:
        db_table = 'movimentacao'
        ordering = ['-data_movimentacao']
        indexes = [
            models.Index(fields=['material', 'data_movimentacao']),
            models.Index(fields=['usuario']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.expressions.RawSQL(
                    "(CASE WHEN solicitacao_id     IS NOT NULL THEN 1 ELSE 0 END) + "
                    "(CASE WHEN entrada_id         IS NOT NULL THEN 1 ELSE 0 END) + "
                    "(CASE WHEN devolucao_id       IS NOT NULL THEN 1 ELSE 0 END) + "
                    "(CASE WHEN item_inventario_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
                    params=[],
                    output_field=models.BooleanField(),
                ),
                name='ck_movimentacao_origem_unica',
            ),
        ]

    def __str__(self):
        return f'{self.tipo} — {self.material.codigo} em {self.data_movimentacao:%d/%m/%Y}'