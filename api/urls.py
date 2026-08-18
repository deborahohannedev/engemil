from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from api.views.core import (
    DemandaViewSet, FornecedorViewSet, MaterialViewSet, MovimentacaoViewSet,
    PerfilViewSet, PostoViewSet, ReferenciaTecnicaViewSet, UnidadeMedidaViewSet,
    UsuarioViewSet,
)
from api.views.dashboard import DashboardResumoView
from api.views.devolucoes import DevolucaoViewSet
from api.views.entradas import EntradaViewSet
from api.views.inventario import InventarioViewSet, ItemInventarioViewSet
from api.views.solicitacoes import SolicitacaoViewSet

router = DefaultRouter()

router.register('materiais', MaterialViewSet, basename='material')
router.register('unidades-medida', UnidadeMedidaViewSet, basename='unidademedida')
router.register('referencias-tecnicas', ReferenciaTecnicaViewSet, basename='referenciatecnica')
router.register('fornecedores', FornecedorViewSet, basename='fornecedor')
router.register('demandas', DemandaViewSet, basename='demanda')
router.register('postos', PostoViewSet, basename='posto')
router.register('usuarios', UsuarioViewSet, basename='usuario')
router.register('perfis', PerfilViewSet, basename='perfil')
router.register('movimentacoes', MovimentacaoViewSet, basename='movimentacao')

router.register('solicitacoes', SolicitacaoViewSet, basename='solicitacao')
router.register('entradas', EntradaViewSet, basename='entrada')
router.register('devolucoes', DevolucaoViewSet, basename='devolucao')
router.register('inventarios', InventarioViewSet, basename='inventario')
router.register('itens-inventario', ItemInventarioViewSet, basename='iteminventario')

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/resumo/', DashboardResumoView.as_view(), name='dashboard-resumo'),
    path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]