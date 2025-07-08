# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a comprehensive Django-based educational platform that combines traditional learning management with AI-powered content creation. The system supports teachers creating courses with hierarchical content structure and students engaging with interactive learning materials.

## Development Commands

### Django Management
```bash
# Run development server
python manage.py runserver

# Database management
python manage.py makemigrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run tests
python manage.py test

# Initialize NCS competencies (required for competency-based assessments)
python manage.py init_ncs_competencies

# Create sample student data for testing
python manage.py create_student_data

# Collect static files
python manage.py collectstatic
```

### Database Operations
- The project uses SQLite3 for development
- Database file: `db.sqlite3`
- Migrations are tracked per app in `*/migrations/`

## Architecture Overview

### Core Django Apps Architecture

**Educational Content Hierarchy:**
```
Course → Chapter → SubChapter → Chasi (Lesson) → ChasiSlide
```

**User Management:**
```
User (Django Auth) → Teacher/Student
School → Class → Students
ClassTeacher (Many-to-Many with roles)
```

**Key Apps:**
- **`accounts`** - Authentication, user roles (Teachers/Students), school/class management
- **`teacher`** - Complete course creation and management system
- **`student`** - Learning interface with progress tracking and interactive assessments
- **`new_cp`** - AI-powered content creation platform (CP Agent)
- **`super_agent`** - Multi-provider AI integration and batch processing
- **`ncs`** - National Competency Standards assessment with adaptive learning
- **`app_home`** - Health habits and physical activity tracking
- **`rolling`** - Student evaluation and rolling assessments

### AI Integration System

The platform uses a multi-provider AI system managed through `super_agent/ai_utils.py`:

**Supported AI Providers:**
- Claude (Anthropic) - Primary content generation
- ChatGPT (OpenAI) - Alternative content generation
- Gemini (Google) - Currently configured with API key
- Grok (X.AI) - Additional provider option

**AI Features:**
- Automatic educational content creation from prompts
- Question generation with answer keys
- Content modification and enhancement
- Template-based content generation
- Batch content processing

### Content Management System

**Content Types Supported:**
- Multiple choice questions
- True/false questions
- Short answer questions
- Essay questions
- Drag-and-drop interactions
- Line matching exercises
- Ordering tasks
- Physical activity records
- One-shot submission formats

**Content Storage:**
- HTML-based content pages
- JSON metadata for question configurations
- File attachments via `ContentsAttached` model
- Media files stored in `media/contents/`

### Interactive Learning Components

**Student Interface Features:**
- Progress tracking per slide/lesson
- Personal note-taking system
- Answer submission with validation
- Real-time feedback and scoring
- Physical activity record submission
- Competency-based adaptive assessments

**Template Structure:**
- Component-based UI with reusable templates
- Slide rendering system for different question types
- Real-time content preview and editing
- Responsive design for mobile/desktop

## Key Development Patterns

### Model Relationships
- Foreign key relationships maintain content hierarchy
- Many-to-many relationships for class-teacher assignments
- JSON fields for flexible metadata storage
- Ordered models with `order` fields for content sequencing

### View Architecture
- Separation of regular views and API views
- Role-based access control throughout
- AJAX endpoints for real-time interactions
- Statistics and analytics views for teachers

### Template Organization
- Base templates with role-specific layouts (`teacher/base.html`, `student/base.html`)
- Component templates in `*/components/` directories
- Versioned templates for feature iterations
- JavaScript modules for interactive components

### Static File Management
- CSS organized by user role and component type
- JavaScript modules for CP Agent content creation
- Image assets for educational content
- Versioned static files for iterative development

## Configuration Notes

### Environment Variables
- `GEMINI_API_KEY` - Currently hardcoded in settings, should be moved to environment
- AI provider keys can be configured via Django settings

### Security Considerations
- CSRF protection enabled (with debugging configuration)
- File upload security measures
- Session management for user authentication
- Role-based view access control

### Development Settings
- `DEBUG = True` for development
- `ALLOWED_HOSTS = ['*']` for local development
- CSRF debugging enabled
- Korean language/timezone settings

## Important Implementation Details

### CP Agent Content Creation
The CP Agent system (`new_cp` app) provides AI-powered content creation with:
- Template-based content generation
- Real-time content editing interface
- Integration with multiple AI providers
- Content validation and preview system

### NCS Competency System
The NCS integration provides:
- Structured competency definitions
- Adaptive learning sessions
- Weakness analysis and targeted recommendations
- Progress tracking against national standards

### Student Assessment Flow
1. Students access courses through assigned course assignments
2. Progress is tracked at the slide level
3. Answers are validated and scored automatically
4. Analytics provide insights for teachers
5. Competency mapping shows learning gaps

## File Upload and Media Handling
- Images uploaded to `media/contents/attachments/`
- Support for GIF, PNG, JPG formats
- File size limits configured in settings
- Temporary file handling for draft content

When working with this codebase, pay attention to the hierarchical content structure, AI integration patterns, and the separation between teacher content creation and student learning interfaces.