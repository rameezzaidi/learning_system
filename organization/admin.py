from django.contrib import admin

from .models import Campus, Region, StudentProfile, SyncRun, SyncSettings

for m in (Region, Campus, StudentProfile, SyncSettings, SyncRun):
    admin.site.register(m)
