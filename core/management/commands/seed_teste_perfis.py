"""
Popula usuarios de teste (um por perfil) pra validar manualmente a matriz
de acesso por funcao. Chamado em build.sh — o ambiente de deploy hoje e
so pra demonstracao/MVP, entao vem populado com esses usuarios de teste
(e o seed_demo, que depende do posto/demanda criados aqui).

Cria 2 ENCARREGADO no MESMO posto de proposito: o escopo do Encarregado e
individual (por solicitante), nao por posto, entao esses dois usuarios
servem pra provar que um nao ve o que o outro criou mesmo compartilhando
posto.

Uso:
    python manage.py seed_teste_perfis
"""
from django.core.management.base import BaseCommand

from core.models import Demanda, Perfil, Posto, Usuario


USUARIOS_TESTE = [
    {
        'cpf': '11122233396',
        'email': 'teste.almoxarifado@engemil.com.br',
        'nome': 'Teste',
        'sobrenome': 'Almoxarifado',
        'funcao': 'ALMOXARIFADO',
        'posto': False,
    },
    {
        'cpf': '22233344405',
        'email': 'teste.encarregado1@engemil.com.br',
        'nome': 'Teste',
        'sobrenome': 'Encarregado Um',
        'funcao': 'ENCARREGADO',
        'posto': True,
    },
    {
        'cpf': '33344455508',
        'email': 'teste.encarregado2@engemil.com.br',
        'nome': 'Teste',
        'sobrenome': 'Encarregado Dois',
        'funcao': 'ENCARREGADO',
        'posto': True,
    },
    {
        'cpf': '44455566619',
        'email': 'teste.engenheiro@engemil.com.br',
        'nome': 'Teste',
        'sobrenome': 'Engenheiro',
        'funcao': 'ENGENHEIRO',
        'posto': False,
    },
]

SENHA_TESTE = 'TesteSenha123!'


class Command(BaseCommand):
    help = 'Popula usuarios de teste (um por perfil) — SOMENTE LOCAL, nao usar em producao.'

    def handle(self, *args, **options):
        self.stdout.write('Criando Posto de teste...')
        posto, criado = Posto.objects.get_or_create(
            codigo='POSTO-TESTE',
            defaults={'nome': 'Posto de Teste', 'descricao': 'Criado por seed_teste_perfis.'},
        )
        self.stdout.write(f"  Posto {'criado' if criado else 'ja existia'}: {posto.codigo}")

        self.stdout.write('Criando Demanda de teste...')
        demanda, criado = Demanda.objects.get_or_create(
            numero='DEMANDA-TESTE',
            defaults={
                'descricao': 'Demanda criada por seed_teste_perfis.',
                'origem': 'Teste manual',
                'situacao': 'ATIVA',
            },
        )
        self.stdout.write(f"  Demanda {'criada' if criado else 'ja existia'}: {demanda.numero}")

        self.stdout.write('')
        self.stdout.write('Criando usuarios de teste...')
        for dados in USUARIOS_TESTE:
            if Usuario.objects.filter(email=dados['email']).exists():
                self.stdout.write(f"  Usuario ja existia: {dados['email']}")
                continue

            perfil = Perfil.objects.get(funcao=dados['funcao'])
            usuario = Usuario.objects.create_user(
                cpf=dados['cpf'],
                email=dados['email'],
                nome=dados['nome'],
                sobrenome=dados['sobrenome'],
                password=SENHA_TESTE,
                perfil=perfil,
                posto=posto if dados['posto'] else None,
            )
            usuario.senha_temporaria = False
            usuario.save(update_fields=['senha_temporaria'])
            self.stdout.write(self.style.SUCCESS(
                f"  Usuario criado: {dados['email']} (CPF {dados['cpf']}, {dados['funcao']})"
            ))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Seed de teste concluido. Senha de todos: {SENHA_TESTE}'))
