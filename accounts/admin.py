from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    # Fields to display in the user list view
    list_display = ("email", "name", "role", "is_staff", "is_active")

    # Fields you can click on to open the user detail view
    list_display_links = ("email", "name")

    # Filter sidebar options
    list_filter = ("role", "is_staff", "is_active")

    # Search bar fields
    search_fields = ("email", "name")

    # Ordering in the list view
    ordering = ("email",)

    # Fields layout when editing an existing user
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal Info", {"fields": ("name", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important Dates", {"fields": ("created_at", "last_login")}),
    )

    # Fields layout when creating a new user via the admin panel
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "name", "role", "password1", "password2"),
            },
        ),
    )

    readonly_fields = ("created_at", "last_login")