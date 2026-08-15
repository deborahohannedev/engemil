"""
Popula dados iniciais obrigatorios: os 6 perfis do sistema e usuarios
administradores de demonstracao.

Uso:
    python manage.py seed_inicial
"""
from django.core.management.base import BaseCommand

from core.models import Perfil, Usuario


PERFIS_PADRAO = [
    ('Encarregado', 'ENCARREGADO'),
    ('Almoxarifado', 'ALMOXARIFADO'),
    ('Compras', 'COMPRAS'),
    ('Engenheiro', 'ENGENHEIRO'),
    ('Administrador', 'ADMINISTRADOR'),
    ('Consulta', 'CONSULTA'),
]

# Trocar as senhas antes de rodar em qualquer ambiente real/exposto.
USUARIOS_ADMIN = [
    {
        'cpf': '12345678909',
        'email': 'admin1@engemil.com.br',
        'nome': 'Admin',
        'sobrenome': 'Um',
        'password': 'TrocarEssaSenha123!',
    },
    {
        'cpf': '98765432100',
        'email': 'admin2@engemil.com.br',
        'nome': 'Admin',
        'sobrenome': 'Dois',
        'password': 'TrocarEssaSenha456!',
    },
]


class Command(BaseCommand):
    help = 'Popula os 6 perfis padrao e cria usuarios administradores de demonstracao.'

    def handle(self, *args, **options):
        self.stdout.write('Populando perfis...')
        for nome, funcao in PERFIS_PADRAO:
            _, criado = Perfil.objects.get_or_create(funcao=funcao, defaults={'nome': nome})
            if criado:
                self.stdout.write(f'  Perfil criado: {nome} ({funcao})')
            else:
                self.stdout.write(f'  Perfil ja existia: {nome} ({funcao})')

        perfil_admin = Perfil.objects.get(funcao='ADMINISTRADOR')

        self.stdout.write('')
        self.stdout.write('Criando usuarios administradores...')
        for dados in USUARIOS_ADMIN:
            if Usuario.objects.filter(email=dados['email']).exists():
                self.stdout.write(f"  Usuario ja existia: {dados['email']}")
                continue

            Usuario.objects.create_superuser(
                cpf=dados['cpf'],
                email=dados['email'],
                nome=dados['nome'],
                sobrenome=dados['sobrenome'],
                password=dados['password'],
                perfil=perfil_admin,
            )
            self.stdout.write(self.style.SUCCESS(f"  Usuario criado: {dados['email']}"))

        self.stdout.write(self.style.SUCCESS('Seed inicial concluido.'))
