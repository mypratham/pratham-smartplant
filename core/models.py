from django.db import models
from django.contrib.auth.models import User

class AIAgent(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=100, default="My AI Agent")
    ai_model_name = models.CharField(max_length=50, default="gemini-3.6-flash")
    api_token = models.CharField(max_length=255, blank=True, null=True)
    system_prompt = models.TextField(blank=True, null=True, default="You are a helpful assistant.")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Device(models.Model):
    plant_id = models.CharField(max_length=100, unique=True, default="pratham_plant_01")
    device_token = models.CharField(max_length=255)
    is_online = models.BooleanField(default=False)
    power_state = models.BooleanField(default=True)
    last_seen = models.DateTimeField(auto_now=True)
    agent = models.ForeignKey(AIAgent, on_delete=models.SET_NULL, null=True, blank=True, related_name="devices")
    
    # Quiz aur state tracking ke liye fields jo humne pehle discuss kiye the
    is_quiz_active = models.BooleanField(default=False)
    quiz_topic = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.plant_id


class KnowledgeBase(models.Model):
    agent = models.ForeignKey(AIAgent, on_delete=models.CASCADE, related_name="knowledge_bases", null=True, blank=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=50, default="Enabled")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Document(models.Model):
    knowledge_base = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="documents")
    name = models.CharField(max_length=255)
    file = models.FileField(upload_to='documents/', blank=True, null=True) # File ke liye
    content = models.TextField(blank=True, null=True) # Extracted text ke liye
    file_size = models.CharField(max_length=50, default="0 KB")
    status = models.CharField(max_length=50, default="Parsed")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.knowledge_base.name} -> {self.name}"


class DocumentChunk(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    chunk_text = models.TextField()
    chunk_index = models.IntegerField(default=1)

    def __str__(self):
        return f"Chunk {self.chunk_index} of {self.document.name}"


class Reminder(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="reminders")
    time = models.CharField(max_length=10)
    message = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.device.plant_id} - {self.time} ({self.message})"


class TouchAction(models.Model):
    ACTION_CHOICES = [
        ('single', 'Single Tap'),
        ('double', 'Double Tap'),
    ]

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="touch_actions")
    action_type = models.CharField(max_length=20, choices=ACTION_CHOICES, default='single')
    text = models.CharField(max_length=100, default="Hi I am Tulsi")
    track_id = models.IntegerField(default=1)
    expression = models.CharField(max_length=20, default="happy")

    def __str__(self):
        return f"{self.device.plant_id} - {self.get_action_type_display()}"


# ==========================================
# NAYA MODEL: Chat History & Cache ke liye
# ==========================================
class PlantChatHistory(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="chat_history")
    user_text = models.TextField(db_index=True)  # Fast lookup ke liye
    ai_response = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.device.plant_id} -> {self.user_text[:30]}"