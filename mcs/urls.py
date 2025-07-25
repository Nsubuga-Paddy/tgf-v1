"""
URL configuration for mcs project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup, name='signup'),
    path('logout/', views.logout_view, name='logout'),
    # Profile URLs
    path('profile/', views.profile_view, name='profile_view'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),

    # 52 Weeks Savings Challenge URLs
    path('52wsc/member-dashboard/', views.wsc_member_dashboard, name='wsc_member_dashboard'),
   
    # Fixed Savings URLs
    path('fsa/', views.individual_fixed_savings_account, name='fsa_dashboard'),
    path('fsa/terms/', views.fixed_savings_terms, name='fsa_terms'),
    # Commercial Goat Farming URLs
    path('goat-farm/', views.goat_farm_dashboard, name='goat_farm_dashboard'),
    path('goat-farm/investment/', views.goat_farm_investment, name='goat_farm_investment'),
    path('goat-farm/transactions/', views.goat_farm_transactions, name='goat_farm_transactions'),
    path('goat-farm/transactions/<str:transaction_id>/details/', views.goat_farm_transaction_details, name='goat_farm_transaction_details'),
    path('goat-farm/performance/', views.goat_farm_performance, name='goat_farm_performance'),
    path('goat-farm/tracking/', views.goat_farm_tracking, name='goat_farm_tracking'),
    # Clubs URLs
    path('clubs/dashboard/<int:club_id>/', views.clubs_dashboard, name='clubs_dashboard'),
    path('clubs/members/<int:club_id>/', views.club_members, name='club_members'),
    path('clubs/transactions/<int:club_id>/', views.club_transactions, name='club_transactions'),
    # RSS URLs
    path('rss/', views.rss_dashboard, name='rss_dashboard'),
    path('rss/portfolio/', views.rss_portfolio, name='rss_portfolio'),
    path('rss/emergency-funds/', views.rss_emergency_funds, name='rss_emergency_funds'),
    
    # GW URLs
    path('gw/portfolio/', views.gw_portfolio, name='gw_portfolio'),
    path('gw/savings/', views.gw_savings, name='gw_savings'),
    
    # Support URL
    path('support/', views.support_view, name='support'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
