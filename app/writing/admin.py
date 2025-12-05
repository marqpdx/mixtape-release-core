from django.contrib import admin

from writing.models import WritingPiece, WritingWorkingCopy


# Register your models here.


@admin.register(WritingWorkingCopy)
class CircleAdmin(admin.ModelAdmin):
    pass
    # list_display = ['slug', 'title', 'summary']
    # search_fields = ['title', 'description', 'created_at', 'group_type']


@admin.register(WritingPiece)
class CircleAdmin(admin.ModelAdmin):
    pass
    # list_display = ['slug', 'title', 'summary']
    # search_fields = ['title', 'description', 'created_at', 'group_type']
