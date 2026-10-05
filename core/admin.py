from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from .models import (
    UserProfile,
    Device, 
    Reminder, 
    TouchAction, 
    KnowledgeBase, 
    Document, 
    DocumentChunk, 
    AIAgent, 
    PlantChatHistory
)

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    fk_name = 'user'  # Zaroori hai kyunki multiple foreign keys hain
    can_delete = False
    verbose_name_plural = 'User Profile & Admin Mapping'

# Agar User pehle se registered hai toh unregister karke custom admin register karein
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'is_staff', 'is_superuser', 'is_active')


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ('plant_id', 'owner_admin', 'assigned_user', 'is_online', 'power_state', 'last_seen')
    search_fields = ('plant_id', 'device_token', 'mac_address')
    list_filter = ('owner_admin', 'is_online')

@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = ('device', 'user', 'time', 'message', 'is_active')
    list_filter = ('is_active',)

@admin.register(TouchAction)
class TouchActionAdmin(admin.ModelAdmin):
    list_display = ('device', 'action_type', 'text', 'track_id', 'expression')

@admin.register(KnowledgeBase)
class KnowledgeBaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'name', 'status', 'created_at')
    search_fields = ('name', 'user')

@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'knowledge_base', 'file_size', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('name', 'content')

@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ('id', 'document', 'chunk_index')
    search_fields = ('chunk_text',)

@admin.register(AIAgent)
class AIAgentAdmin(admin.ModelAdmin):
    list_display = ('name', 'ai_model_name', 'user', 'created_at')
    search_fields = ('name', 'ai_model_name')

@admin.register(PlantChatHistory)
class PlantChatHistoryAdmin(admin.ModelAdmin):
    list_display = ('device', 'user_text', 'ai_response', 'created_at')
    search_fields = ('user_text', 'ai_response')
    list_filter = ('created_at',)