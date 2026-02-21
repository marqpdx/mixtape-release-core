# earthlab/admin.py

from django.contrib import admin
from .models import Course, Lesson, CourseItem, CourseRun, Enrollment, LessonProgress, ModuleProgress


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


class EnrollmentInline(admin.TabularInline):
    model = Enrollment
    extra = 0
    fields = ("user", "status", "enrolled_at", "completed_at")
    readonly_fields = ("enrolled_at",)


@admin.register(CourseRun)
class CourseRunAdmin(admin.ModelAdmin):
    list_display = ("course", "title", "status", "enrollment_policy", "start_date", "end_date")
    list_filter = ("status", "enrollment_policy")
    search_fields = ("title", "course__title")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [EnrollmentInline]


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("user", "course_run", "status", "enrolled_at", "completed_at")
    list_filter = ("status",)
    search_fields = ("user__username", "course_run__course__title")
    readonly_fields = ("id", "enrolled_at", "created_at", "updated_at")
