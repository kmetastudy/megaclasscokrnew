from django.contrib import admin
from django import forms
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import path, reverse
import json

from .models import (
    Course, Chapter, SubChapter, Chasi, CourseAssignment, 
    ContentType, Contents, ChasiSlide, ContentsAttached,ContentTypeCategory
)

from accounts.models import Class, Student  # accounts 앱에서 import

class BulkCourseAssignmentForm(forms.Form):
    courses = forms.ModelMultipleChoiceField(
        label='할당할 코스',
        queryset=Course.objects.none(),
        widget=FilteredSelectMultiple('코스', is_stacked=False),
        help_text='여러 코스를 선택할 수 있습니다.',
    )
    classes = forms.ModelMultipleChoiceField(
        label='할당할 학급',
        queryset=Class.objects.none(),
        widget=FilteredSelectMultiple('학급', is_stacked=False),
        help_text='여러 학급을 선택할 수 있습니다.',
    )
    due_date = forms.DateTimeField(
        label='마감일',
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['courses'].queryset = Course.objects.order_by('subject_name', 'target')
        self.fields['classes'].queryset = Class.objects.select_related('school').order_by(
            'school__name',
            'grade',
            'class_number',
            'name',
        )

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['subject_name', 'target', 'teacher', 'is_active', 'created_at']
    list_filter = ['is_active', 'teacher', 'created_at']
    search_fields = ['subject_name', 'target', 'description']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if hasattr(request.user, 'teacher'):
            return qs.filter(teacher=request.user.teacher)
        return qs.none()

@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ['chapter_title', 'subject', 'chapter_order', 'created_at']
    list_filter = ['subject', 'created_at']
    search_fields = ['chapter_title', 'description']
    ordering = ['subject', 'chapter_order']
    readonly_fields = ['created_at', 'updated_at']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if hasattr(request.user, 'teacher'):
            return qs.filter(subject__teacher=request.user.teacher)
        return qs.none()

@admin.register(SubChapter)
class SubChapterAdmin(admin.ModelAdmin):
    list_display = ['sub_chapter_title', 'chapter', 'sub_chapter_order', 'created_at']
    list_filter = ['chapter__subject', 'created_at']
    search_fields = ['sub_chapter_title', 'description']
    ordering = ['chapter', 'sub_chapter_order']
    readonly_fields = ['created_at', 'updated_at']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if hasattr(request.user, 'teacher'):
            return qs.filter(subject__teacher=request.user.teacher)
        return qs.none()

@admin.register(Chasi)
class ChasiAdmin(admin.ModelAdmin):
    list_display = ['chasi_title', 'subject', 'chapter', 'sub_chapter', 'chasi_order', 'duration_minutes', 'is_published', 'created_at']
    list_filter = ['is_published', 'subject', 'created_at']
    search_fields = ['chasi_title', 'description', 'learning_objectives']
    ordering = ['subject', 'chasi_order']
    readonly_fields = ['created_at', 'updated_at']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if hasattr(request.user, 'teacher'):
            return qs.filter(subject__teacher=request.user.teacher)
        return qs.none()

@admin.register(CourseAssignment)
class CourseAssignmentAdmin(admin.ModelAdmin):
    change_list_template = 'admin/teacher/courseassignment/change_list.html'
    list_display = ['course', 'get_assigned_to', 'get_assigned_type', 'assigned_at', 'due_date', 'is_completed']
    list_filter = ['is_completed', 'assigned_at', 'due_date']
    search_fields = ['course__subject_name', 'assigned_class__name', 'assigned_student__user__first_name', 'assigned_student__user__last_name']
    ordering = ['-assigned_at']
    date_hierarchy = 'assigned_at'
    
    def get_assigned_to(self, obj):
        """할당 대상 표시"""
        if obj.assigned_class:
            return f"학급: {obj.assigned_class.name}"
        elif obj.assigned_student:
            return f"학생: {obj.assigned_student.user.get_full_name()}"
        return "-"
    get_assigned_to.short_description = '할당 대상'
    
    def get_assigned_type(self, obj):
        """할당 타입 표시"""
        if obj.assigned_class:
            return "학급"
        elif obj.assigned_student:
            return "개인"
        return "-"
    get_assigned_type.short_description = '할당 타입'
    
    fieldsets = (
        ('코스 정보', {
            'fields': ('course',)
        }),
        ('할당 대상', {
            'fields': ('assigned_class', 'assigned_student'),
            'description': '학급 또는 학생 중 하나만 선택하세요.'
        }),
        ('할당 정보', {
            'fields': ('due_date', 'is_completed', 'completed_at')
        }),
    )

    readonly_fields = ['assigned_at', 'completed_at']

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'bulk-assign/',
                self.admin_site.admin_view(self.bulk_assign_view),
                name='teacher_courseassignment_bulk_assign',
            ),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        if request.user.is_superuser:
            extra_context['bulk_assign_url'] = reverse('admin:teacher_courseassignment_bulk_assign')
        return super().changelist_view(request, extra_context=extra_context)

    def bulk_assign_view(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied

        if request.method == 'POST':
            form = BulkCourseAssignmentForm(request.POST)
            if form.is_valid():
                courses = form.cleaned_data['courses']
                classes = form.cleaned_data['classes']
                due_date = form.cleaned_data['due_date']
                created_count, skipped_count = self.create_bulk_assignments(courses, classes, due_date)
                self.message_user(
                    request,
                    f'코스 할당 {created_count}개를 생성했고, 기존 할당 {skipped_count}개는 건너뛰었습니다.',
                )
                return redirect('admin:teacher_courseassignment_changelist')
        else:
            form = BulkCourseAssignmentForm()

        context = {
            **self.admin_site.each_context(request),
            'title': '코스 대량 할당',
            'form': form,
            'opts': self.model._meta,
            'media': self.media + form.media,
        }
        return render(request, 'admin/teacher/courseassignment/bulk_assign.html', context)

    def create_bulk_assignments(self, courses, classes, due_date):
        course_ids = list(courses.values_list('id', flat=True))
        class_ids = list(classes.values_list('id', flat=True))

        existing_pairs = set(
            CourseAssignment.objects.filter(
                course_id__in=course_ids,
                assigned_class_id__in=class_ids,
            ).values_list('course_id', 'assigned_class_id')
        )

        new_assignments = [
            CourseAssignment(course_id=course_id, assigned_class_id=class_id, due_date=due_date)
            for course_id in course_ids
            for class_id in class_ids
            if (course_id, class_id) not in existing_pairs
        ]

        with transaction.atomic():
            CourseAssignment.objects.bulk_create(new_assignments)

        return len(new_assignments), len(course_ids) * len(class_ids) - len(new_assignments)

@admin.register(ContentTypeCategory)
class ContentTypeCategoryAdmin(admin.ModelAdmin):
    list_display = ['category_name', 'description', 'icon', 'color']
    list_filter = []
    search_fields = ['category_name', 'description']
    ordering = ['category_name']

@admin.register(ContentType)
class ContentTypeAdmin(admin.ModelAdmin):
    list_display = ['type_name','category_name', 'description', 'icon', 'color', 'is_active']
    list_filter = ['is_active']
    search_fields = ['type_name','category_name', 'description']
    ordering = ['type_name']

class ContentsAdminForm(forms.ModelForm):
    class Meta:
        model = Contents
        fields = '__all__'
    
    def clean_tags(self):
        tags = self.cleaned_data.get('tags')
        
        # tags가 딕셔너리가 아닌 경우 처리
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                raise forms.ValidationError('tags는 유효한 JSON 형식이어야 합니다.')
        
        # 필수 필드 검증
        required_fields = ['competency', 'sub_competency']
        for field in required_fields:
            if field not in tags:
                raise forms.ValidationError(f'{field}는 필수 항목입니다.')
        
        return tags

@admin.register(Contents)
class ContentsAdmin(admin.ModelAdmin):
    form = ContentsAdminForm
    list_display = ['title', 'content_type', 'get_competency', 'get_sub_competency', 'is_active']
    list_filter = ['content_type', 'is_active']
    search_fields = ['title', 'tags']
    
    def get_competency(self, obj):
        tags = obj.tags or {}
        return tags.get('competency', '-')
    get_competency.short_description = '역량'
    
    def get_sub_competency(self, obj):
        tags = obj.tags or {}
        return tags.get('sub_competency', '-')
    get_sub_competency.short_description = '세부역량'
    

# @admin.register(Contents)
# class ContentsAdmin(admin.ModelAdmin):
#     list_display = ['title', 'content_type', 'created_by', 'created_at', 'is_active','is_public']
#     list_filter = ['content_type', 'is_active', 'created_at','is_public']
#     search_fields = ['title', 'page','is_public']
#     date_hierarchy = 'created_at'
#     readonly_fields = ['created_at', 'updated_at']
    
#     fieldsets = (
#         ('기본 정보', {
#             'fields': ('content_type', 'title', 'is_active')
#         }),
#         ('콘텐츠', {
#             'fields': ('page', 'answer')
#         }),
#         ('메타데이터', {
#             'fields': ('meta_data', 'tags'),
#             'classes': ('collapse',)
#         }),
#         ('시스템 정보', {
#             'fields': ('created_by', 'created_at', 'updated_at'),
#             'classes': ('collapse',)
#         }),
#     )
    
#     def save_model(self, request, obj, form, change):
#         if not obj.created_by:
#             obj.created_by = request.user
#         super().save_model(request, obj, form, change)

@admin.register(ChasiSlide)
class ChasiSlideAdmin(admin.ModelAdmin):
    """차시 슬라이드 관리자"""
    list_display = ['id','get_chasi_title', 'slide_number', 'slide_title', 'content_type', 'get_content_title', 'estimated_time', 'is_active']
    list_filter = ['content_type', 'is_active', 'created_at']
    search_fields = ['slide_title', 'chasi__chasi_title', 'content__title']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at', 'updated_at']
    
    def get_chasi_title(self, obj):
        return obj.chasi.chasi_title
    get_chasi_title.short_description = '차시'
    get_chasi_title.admin_order_field = 'chasi__chasi_title'
    
    def get_content_title(self, obj):
        return obj.content.title
    get_content_title.short_description = '콘텐츠'
    get_content_title.admin_order_field = 'content__title'
    
    fieldsets = (
        ('기본 정보', {
            'fields': ('chasi', 'slide_number', 'slide_title', 'is_active')
        }),
        ('콘텐츠', {
            'fields': ('content_type', 'content')
        }),
        ('추가 정보', {
            'fields': ('instructor_notes', 'estimated_time')
        }),
        ('시스템 정보', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(ContentsAttached)
class ContentsAttachedAdmin(admin.ModelAdmin):
    list_display = ['contents', 'original_name', 'file_type', 'file_size', 'uploaded_at']
    list_filter = ['file_type', 'uploaded_at']
    search_fields = ['original_name', 'contents__title']
    readonly_fields = ['uploaded_at']
    ordering = ['-uploaded_at']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if hasattr(request.user, 'teacher'):
            return qs.filter(contents__created_by=request.user)
        return qs.none()

# 인라인 클래스들
class ChapterInline(admin.TabularInline):
    model = Chapter
    extra = 0
    fields = ['chapter_title', 'chapter_order', 'description']
    ordering = ['chapter_order']

class SubChapterInline(admin.TabularInline):
    model = SubChapter
    extra = 0
    fields = ['sub_chapter_title', 'sub_chapter_order', 'description']
    ordering = ['sub_chapter_order']

class ChasiInline(admin.TabularInline):
    model = Chasi
    extra = 0
    fields = ['chasi_title', 'chasi_order', 'duration_minutes', 'is_published']
    ordering = ['chasi_order']

class ChasiSlideInline(admin.TabularInline):
    model = ChasiSlide
    extra = 0
    fields = ['slide_number', 'slide_title', 'content_type', 'content', 'estimated_time']
    ordering = ['slide_number']

# 인라인을 기존 admin에 추가
CourseAdmin.inlines = [ChapterInline]
ChapterAdmin.inlines = [SubChapterInline]
SubChapterAdmin.inlines = [ChasiInline]
ChasiAdmin.inlines = [ChasiSlideInline]
