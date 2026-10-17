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


# ---------------- Device contacts (bulk upload) + Device settings ----------------
import csv as _csv
import io as _io

from django import forms as _forms
from django.contrib import messages as _messages
from django.shortcuts import redirect as _redirect, render as _render
from django.urls import path as _path

from core.models import Device as _Device, DeviceContact as _DeviceContact, DeviceSettings as _DeviceSettings


def import_contacts_csv(device, text, max_contacts=500):
    """CSV text -> device ke contacts. Return (added, updated, skipped)."""
    from core.views import _clean_contact
    rows = list(_csv.DictReader(_io.StringIO(text.lstrip("﻿"))))

    def pick(row, *names):
        low = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items() if k}
        for n in names:
            v = low.get(n)
            if v:
                return v.split(" ::: ")[0].strip()
        return ""

    existing = {c.name.lower(): c for c in _DeviceContact.objects.filter(device=device)}
    added = updated = skipped = 0
    for row in rows:
        name = pick(row, "name", "full name", "display name") or " ".join(
            x for x in (pick(row, "first name", "given name"), pick(row, "middle name", "additional name"),
                        pick(row, "last name", "family name")) if x)
        data, errors = _clean_contact({
            "name": name,
            "aliases": pick(row, "aliases", "alias", "nickname"),
            "email": pick(row, "email", "e-mail", "e-mail 1 - value", "email 1 - value", "e-mail address"),
            "phone": pick(row, "phone", "mobile", "whatsapp", "phone 1 - value", "mobile phone", "primary phone"),
        })
        if errors:
            skipped += 1
            continue
        c = existing.get(data["name"].lower())
        if c is not None:
            changed = False
            for k in ("email", "phone", "aliases"):
                if data[k] and getattr(c, k) != data[k]:
                    setattr(c, k, data[k])
                    changed = True
            if changed:
                c.save()
                updated += 1
            continue
        if len(existing) >= max_contacts:
            skipped += 1
            continue
        c = _DeviceContact.objects.create(device=device, **data)
        existing[c.name.lower()] = c
        added += 1
    return added, updated, skipped


class _ContactCsvForm(_forms.Form):
    device = _forms.ModelChoiceField(queryset=_Device.objects.exclude(plant_id__startswith="loadtest").order_by("plant_id"),
                                     to_field_name="plant_id")
    csv_file = _forms.FileField(label="CSV file", help_text="Columns: name, email, phone, aliases (ya Google CSV). 2 MB tak.")


@admin.register(_DeviceContact)
class DeviceContactAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "aliases", "device")
    list_filter = ("device",)
    search_fields = ("name", "aliases", "email", "phone", "device__plant_id")
    list_select_related = ("device",)
    list_per_page = 100
    change_list_template = "admin/core/devicecontact/change_list.html"

    def get_urls(self):
        return [_path("bulk-upload/", self.admin_site.admin_view(self.bulk_upload),
                      name="core_devicecontact_bulk")] + super().get_urls()

    def bulk_upload(self, request):
        form = _ContactCsvForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            f = form.cleaned_data["csv_file"]
            if f.size > 2_000_000:
                form.add_error("csv_file", "File 2 MB se badi hai")
            else:
                raw = f.read()
                for enc in ("utf-8-sig", "utf-16", "cp1252"):
                    try:
                        text = raw.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    text = None
                if text is None:
                    form.add_error("csv_file", "File padh nahi paaye: CSV (UTF-8) mein save karein")
                else:
                    dev = form.cleaned_data["device"]
                    added, updated, skipped = import_contacts_csv(dev, text)
                    self.message_user(request, f"{dev.plant_id}: naye {added}, update {updated}, chhode {skipped}",
                                      _messages.SUCCESS if added or updated else _messages.WARNING)
                    return _redirect(f"../?device__id__exact={dev.pk}")
        ctx = {**self.admin_site.each_context(request), "form": form, "title": "Contacts bulk upload (CSV)",
               "opts": self.model._meta}
        return _render(request, "admin/core/devicecontact/bulk_upload.html", ctx)


@admin.register(_DeviceSettings)
class DeviceSettingsAdmin(admin.ModelAdmin):
    # Secrets (keys / passwords) admin mein bhi nahi dikhte; badalne ke liye /device-settings/ page
    list_display = ("device", "assistant_name", "ai_provider", "ai_model", "gmail_address", "whatsapp_phone", "updated_at")
    search_fields = ("device__plant_id", "assistant_name", "gmail_address")
    fields = ("device", "assistant_name", "ai_provider", "ai_model", "gmail_address", "mail_sender_name",
              "whatsapp_phone", "updated_at")
    readonly_fields = ("device", "ai_provider", "ai_model", "gmail_address", "whatsapp_phone", "updated_at")

    def has_add_permission(self, request):
        return False


# ---- Device notices (admin ke message) ----
from django.db.models import Count as _Count
from core.models import DeviceNotice as _DeviceNotice


@admin.register(_DeviceNotice)
class DeviceNoticeAdmin(admin.ModelAdmin):
    list_display = ("id", "kisko", "title", "message", "speak", "pahuncha", "cancelled", "created_at", "expires_at")
    list_filter = ("cancelled", "speak")
    search_fields = ("message", "title", "target__plant_id")
    raw_id_fields = ("target",)
    readonly_fields = ("created_by", "created_at")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("target").annotate(_n=_Count("deliveries"))

    @admin.display(description="Kisko")
    def kisko(self, obj):
        return obj.target.plant_id if obj.target_id else "SAB devices"

    @admin.display(description="Pahuncha", ordering="_n")
    def pahuncha(self, obj):
        return obj._n

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
