from django.contrib import admin

from core.models import (
    Demanda, Fornecedor, Material, Movimentacao,
    Perfil, Posto, ReferenciaTecnica, UnidadeMedida, Usuario,
)

admin.site.register(Perfil)
admin.site.register(Posto)
admin.site.register(Usuario)
admin.site.register(UnidadeMedida)
admin.site.register(ReferenciaTecnica)
admin.site.register(Fornecedor)
admin.site.register(Demanda)
admin.site.register(Material)
admin.site.register(Movimentacao)