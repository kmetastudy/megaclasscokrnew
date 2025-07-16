# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django import forms
from .models import School, Teacher, Class, Student,ClassTeacher


class TeacherPasswordChangeForm(forms.ModelForm):
    """교사 비밀번호 변경을 위한 커스텀 폼"""
    new_password = forms.CharField(
        label='새 비밀번호',
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '새 비밀번호를 입력하세요 (예: 1234)'
        }),
        help_text='비어있으면 비밀번호를 변경하지 않습니다. 간단한 비밀번호(예: 1234)도 설정 가능합니다.'
    )
    confirm_password = forms.CharField(
        label='비밀번호 확인',
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '비밀번호를 다시 입력하세요'
        })
    )

    class Meta:
        model = Teacher
        fields = ['user', 'school', 'employee_id', 'phone']

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if new_password or confirm_password:
            if new_password != confirm_password:
                raise forms.ValidationError('비밀번호가 일치하지 않습니다.')
        
        return cleaned_data

    def save(self, commit=True):
        # Django admin will handle password change in save_model()
        # Just save the Teacher model normally here
        teacher = super().save(commit=commit)
        return teacher

@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ['name', 'address', 'created_at']
    search_fields = ['name', 'address']
    list_filter = ['created_at']

class TeacherInline(admin.StackedInline):
    model = Teacher
    can_delete = False
    verbose_name_plural = '교사 정보'

# ★★★ ClassTeacher 모델을 Class Admin에 인라인으로 추가 ★★★
class ClassTeacherInline(admin.TabularInline):
    model = ClassTeacher
    extra = 1  # 기본으로 보여줄 추가 폼 개수
    autocomplete_fields = ['teacher'] # 교사 검색 기능 추가


class StudentInline(admin.StackedInline):
    model = Student
    can_delete = False
    verbose_name_plural = '학생 정보'

class CustomUserAdmin(UserAdmin):
    inlines = (TeacherInline, StudentInline)
    
    def get_inline_instances(self, request, obj=None):
        if not obj:
            return list()
        return super().get_inline_instances(request, obj)

# User 모델 재등록
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)

@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    form = TeacherPasswordChangeForm
    list_display = ['user', 'school', 'employee_id', 'phone', 'created_at']
    list_filter = ['school', 'created_at']
    search_fields = ['user__username', 'user__first_name', 'user__last_name', 'employee_id']
    raw_id_fields = ['user']
    
    fieldsets = (
        ('기본 정보', {
            'fields': ('user', 'school', 'employee_id', 'phone')
        }),
        ('비밀번호 변경', {
            'fields': ('new_password', 'confirm_password'),
            'description': '관리자가 교사의 비밀번호를 변경할 수 있습니다. 간단한 비밀번호(예: 1234)도 설정 가능합니다.'
        }),
    )
    
    def save_model(self, request, obj, form, change):
        """관리자가 저장할 때 호출되는 메서드 - 여기서 비밀번호 변경 처리"""
        # 먼저 Teacher 모델 저장
        super().save_model(request, obj, form, change)
        
        # 비밀번호 변경 처리
        new_password = form.cleaned_data.get('new_password')
        if new_password:
            print(f"DEBUG: Changing password for user {obj.user.username} to: {new_password}")
            # set_password()를 사용하여 Django의 AUTH_PASSWORD_VALIDATORS를 우회
            obj.user.set_password(new_password)
            obj.user.save()
            print(f"DEBUG: Password changed and user saved")
            
            self.message_user(
                request, 
                f'{obj.user.get_full_name()} 교사의 비밀번호가 성공적으로 변경되었습니다.',
                level='SUCCESS'
            )
        else:
            print(f"DEBUG: No password change requested")

@admin.register(Class)
class ClassAdmin(admin.ModelAdmin):
    # ★★★ [수정] list_display와 search_fields 변경 ★★★
    list_display = ['name', 'school', 'grade', 'class_number', 'get_main_teacher_name', 'student_count']
    list_filter = ['school', 'grade']
    search_fields = ['name', 'teachers__user__username'] # 'teacher' -> 'teachers'
    inlines = [ClassTeacherInline] # 인라인 추가

    def student_count(self, obj):
        return obj.student_set.count()
    student_count.short_description = '학생 수'

    def get_main_teacher_name(self, obj):
        main_teacher = obj.get_main_teacher()
        return main_teacher.user.get_full_name() if main_teacher else '미지정'
    get_main_teacher_name.short_description = '담임 교사'



@admin.register(ClassTeacher)
class ClassTeacherAdmin(admin.ModelAdmin):
    """(선택사항) ClassTeacher 모델을 직접 관리할 경우"""
    list_display = ['class_instance', 'teacher', 'role']
    list_filter = ['role']
    search_fields = ['class_instance__name', 'teacher__user__username']

# @admin.register(Class)
# class ClassAdmin(admin.ModelAdmin):
#     list_display = ['name', 'school', 'grade', 'class_number', 'teacher', 'student_count']
#     list_filter = ['school', 'grade', 'created_at']
#     search_fields = ['name', 'teacher__user__username']
    
#     def student_count(self, obj):
#         return obj.student_set.count()
#     student_count.short_description = '학생 수'

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ['user', 'school_class', 'student_id', 'birth_date', 'created_at']
    list_filter = ['school_class__school', 'school_class__grade', 'created_at']
    search_fields = ['user__username', 'user__first_name', 'user__last_name', 'student_id']
    raw_id_fields = ['user']