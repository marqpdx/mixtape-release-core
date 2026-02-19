# earthlab/admin.py

from django.contrib import admin
from .models import Course, Lesson, CourseItem


class CourseItemInline(admin.TabularInline):
    model = CourseItem
    extra = 1
    fields = ("position", "content_type", "content_object_id", "section_title")
    ordering = ("position",)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "delivery_type", "difficulty_level", "flow_mode", "updated_at")
    list_filter = ("status", "delivery_type", "difficulty_level")
    search_fields = ("title", "summary")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [CourseItemInline]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "difficulty_level", "estimated_duration", "updated_at")
    list_filter = ("status", "difficulty_level")
    search_fields = ("title", "summary")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(CourseItem)
class CourseItemAdmin(admin.ModelAdmin):
    list_display = ("course", "position", "content_type", "content_object_id", "section_title")
    list_filter = ("content_type",)
    ordering = ("course", "position")
