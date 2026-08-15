import re

from django.core.exceptions import ValidationError


def validar_cpf(cpf: str) -> None:
    """
    Valida formato e dígitos verificadores de um CPF.
    Aceita com ou sem pontuação (000.000.000-00 ou 00000000000).
    """
    digitos = re.sub(r'\D', '', cpf or '')

    if len(digitos) != 11:
        raise ValidationError('CPF deve ter 11 dígitos.')

    if digitos == digitos[0] * 11:
        raise ValidationError('CPF inválido.')

    def calcular_digito(cpf_parcial: str, peso_inicial: int) -> int:
        soma = sum(int(d) * peso for d, peso in zip(cpf_parcial, range(peso_inicial, 1, -1)))
        resto = (soma * 10) % 11
        return 0 if resto == 10 else resto

    digito1 = calcular_digito(digitos[:9], 10)
    digito2 = calcular_digito(digitos[:10], 11)

    if digitos[-2:] != f'{digito1}{digito2}':
        raise ValidationError('CPF inválido — dígitos verificadores não conferem.')
    
def validar_telefone(telefone: str) -> None:
    """
    Valida telefone brasileiro (fixo ou celular), com DDD.
    Aceita com ou sem pontuação/parênteses.
    Fixo: 10 dígitos (DDD + 8). Celular: 11 dígitos (DDD + 9, começando com 9).
    """
    if not telefone:
        return  # campo opcional — validação só roda se algo foi informado

    digitos = re.sub(r'\D', '', telefone)

    if len(digitos) not in (10, 11):
        raise ValidationError('Telefone deve ter 10 ou 11 dígitos, incluindo o DDD.')

    ddd = int(digitos[:2])
    if ddd < 11 or ddd > 99:
        raise ValidationError('DDD inválido.')

    if len(digitos) == 11 and digitos[2] != '9':
        raise ValidationError('Celular deve começar com 9 após o DDD.')


UNIDADES_CONTAVEIS = {'un', 'pct', 'cx'}


def validar_quantidade_por_unidade(quantidade, unidade) -> None:
    """
    Quantidade deve ser inteira pra unidades contáveis (un, pct, cx) — fração
    só faz sentido pra unidades contínuas (m, m2, m3, cm2, cm3, kg).
    """
    if unidade.sigla in UNIDADES_CONTAVEIS and quantidade % 1 != 0:
        raise ValidationError(
            f'Quantidade deve ser um número inteiro para a unidade "{unidade.sigla}".'
        )