from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),

    # Devices API
    path("api/devices/", include("devices.urls")),
    path("api/", include("accounts.urls")),
]