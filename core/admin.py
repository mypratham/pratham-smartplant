from django.contrib import admin
from .models import (
    Device, 
    Reminder, 
    TouchAction, 
    KnowledgeBase, 
    Document, 
    DocumentChunk, 
    AIAgent, 
    PlantChatHistory
)

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ('plant_id', 'is_online', 'power_state', 'last_seen')
    search_fields = ('plant_id', 'device_token')

@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = ('device', 'time', 'message', 'is_active')
    list_filter = ('is_active',)

@admin.register(TouchAction)
class TouchActionAdmin(admin.ModelAdmin):
    list_display = ('device', 'action_type', 'text', 'track_id', 'expression')

@admin.register(KnowledgeBase)
class KnowledgeBaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'status', 'created_at')
    search_fields = ('name',)

@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'knowledge_base', 'file_size', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('name', 'content')

@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ('id', 'document', 'chunk_index')
    search_fields = ('chunk_text',)

# --- Purane aur zaroori models jo admin mein wapas jode gaye hain ---
@admin.register(AIAgent)
class AIAgentAdmin(admin.ModelAdmin):
    list_display = ('name', 'ai_model_name', 'user', 'created_at')
    search_fields = ('name', 'ai_model_name')

@admin.register(PlantChatHistory)
class PlantChatHistoryAdmin(admin.ModelAdmin):
    list_display = ('device', 'user_text', 'ai_response', 'created_at')
    search_fields = ('user_text', 'ai_response')
    list_filter = ('created_at',)