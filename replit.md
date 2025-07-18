# OBYRA IA - Construction Management Platform

## Overview

OBYRA IA is a comprehensive web platform designed for construction companies, architects, and construction firms in Argentina and Latin America. The system automates project management, team coordination, budgeting, and construction documentation. Built with Flask and SQLAlchemy, it provides a modular architecture for managing the complete construction workflow.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend Architecture
- **Technology**: Flask with Jinja2 templating
- **UI Framework**: Bootstrap 5 for responsive design
- **JavaScript**: Vanilla JavaScript with Chart.js for data visualization
- **Styling**: Custom CSS with construction industry theming
- **Icons**: Font Awesome for consistent iconography

### Backend Architecture
- **Framework**: Flask (Python web framework)
- **Database ORM**: SQLAlchemy with Flask-SQLAlchemy extension
- **Authentication**: Flask-Login for session management
- **Password Security**: Werkzeug password hashing
- **Application Structure**: Blueprint-based modular architecture

### Database Architecture
- **Primary Database**: SQLite (development), configurable for PostgreSQL production
- **ORM**: SQLAlchemy with declarative base model
- **Connection Pooling**: Configured with pool recycling and pre-ping
- **Models**: User management, projects (obras), budgets, inventory, time tracking

## Key Components

### Authentication System
- Role-based access control (Administrator, Technician, Operator)
- Session management with Flask-Login
- Permission-based module access control
- User registration restricted to administrators

### Project Management (Obras)
- Complete project lifecycle management
- Client information and contact details
- Project status tracking (planning, in-progress, paused, finished, cancelled)
- Team assignment and role management
- Timeline and milestone tracking

### Budget Management (Presupuestos)
- Detailed budget creation and item management
- PDF generation for client proposals using ReportLab
- VAT calculation and tax handling
- Integration with project data
- Status workflow (draft, sent, approved, rejected)

### Team Management (Equipos)
- User profile management
- Performance tracking and reporting
- Work assignment by project
- Role-based dashboard access
- Time tracking and productivity metrics

### Inventory Control (Inventario)
- Material, tool, and machinery tracking
- Category-based organization
- Stock level monitoring with low-stock alerts
- Usage tracking by project
- Movement history and audit trail

### Reporting System (Reportes)
- Comprehensive dashboard with KPIs
- Date-range filtering for analytics
- Project status summaries
- Team performance metrics
- Inventory status reports

## Data Flow

### User Authentication Flow
1. User logs in through `/login` endpoint
2. Credentials validated against hashed passwords
3. Session created with Flask-Login
4. Role-based permissions checked for module access
5. Redirected to dashboard or requested page

### Project Management Flow
1. Projects created by administrators or technicians
2. Team members assigned to projects
3. Project status tracked through defined workflows
4. Time and resource usage recorded
5. Progress reported through dashboard analytics

### Budget Creation Flow
1. Budget linked to existing project
2. Line items added with quantities and costs
3. Automatic calculations including VAT
4. PDF generation for client presentation
5. Status tracking through approval workflow

## External Dependencies

### Python Packages
- **Flask**: Web application framework
- **Flask-SQLAlchemy**: Database ORM integration
- **Flask-Login**: User session management
- **Werkzeug**: WSGI utilities and security functions
- **ReportLab**: PDF generation for budgets and reports

### Frontend Libraries
- **Bootstrap 5**: CSS framework for responsive design
- **Font Awesome**: Icon library
- **Chart.js**: JavaScript charting library for analytics

### Development Tools
- **SQLite**: Development database (configurable for PostgreSQL)
- **Jinja2**: Template engine (included with Flask)

## Deployment Strategy

### Environment Configuration
- Environment variables for database URL and session secrets
- Debug mode configurable for development/production
- WSGI application with ProxyFix middleware for reverse proxy deployment

### Database Strategy
- SQLite for local development and testing
- PostgreSQL recommended for production deployment
- Database migrations handled through SQLAlchemy
- Connection pooling configured for production scalability

### Security Considerations
- Password hashing with Werkzeug security functions
- Session management with secure secret keys
- Role-based access control throughout the application
- CSRF protection through Flask's built-in mechanisms

### Scalability Approach
- Modular blueprint architecture for easy feature extension
- Database connection pooling for concurrent users
- Static asset optimization with CDN-ready structure
- Caching strategy ready for Redis integration

The system is designed to be deployed on platforms like Replit, with easy configuration for database connections and scaling requirements.

## Recent Changes (July 2025)

### Menu Optimization and Corporate Branding (Latest Update)
- **Simplified Asistente IA Menu**: Cleaned up navigation by removing redundant items (Configuración Inteligente, Calculadora Inteligente, Análisis de Rendimiento, Diagnóstico IA Local)
- **New INICIO Section**: Created professional landing page with corporate glass-effect styling using provided corporate image
- **Streamlined Navigation**: Menu now contains only "INICIO" and "Auditoría IA (Super Admin)" for focused user experience
- **Corporate Image Integration**: Implemented glassmorphism design with the provided architectural corporate background
- **Enhanced User Experience**: Professional call-to-action button "Solicitá tu Asesoría" with hover effects and animations

## Recent Changes (July 2025)

### Complete Authentication System Implementation
- **Manual Registration & Login**: Full user registration with validations, password hashing, and auto-login
- **Google OAuth Integration**: Authlib-based OAuth2 with automatic user creation and profile sync
- **Automatic Profile Creation**: When logging in with Google, the system automatically creates complete user profiles including first name, last name, and profile picture from Google account
- **Profile Picture Integration**: Google profile pictures are automatically saved and displayed in navigation bar, user profiles, team listings, and AI chat interface
- **Database Schema Updates**: Added auth_provider, google_id, profile_picture, created_at fields
- **Secure Authentication**: Flask-Login integration with role-based access control
- **Administrative Registration**: Special route for admins to create team accounts
- **Template System**: Responsive authentication forms with consistent UX and profile picture display
- **Error Handling**: Graceful handling when Google OAuth credentials not configured
- **Dynamic Profile Updates**: User profile information and pictures are automatically updated on each Google login to keep data current

### Organization-Based Multi-Tenancy System (Latest Update)
- **Organization Model**: New Organizacion table with automatic token generation for invitations
- **Multi-Tenant Architecture**: Users are grouped by organizations with complete data isolation
- **Automatic Organization Creation**: New users automatically get their own organization and admin role
- **Invitation System**: Administrators can invite users via email or shareable invitation links
- **Role-Based Access Control**: Organization-scoped permissions with admin, technician, and operator roles
- **Data Isolation**: All queries filtered by organization_id to ensure data privacy
- **Email Conflict Prevention**: Users with existing emails must be invited to join organizations
- **Database Migration**: Automatic migration of existing users to organization-based structure
- **White-List Admin Assignment**: Specific emails automatically assigned administrator roles
- **Comprehensive User Management**: Admin panel with filtering, role changes, and user activation/deactivation

### Intelligent Project Configuration System
- **Enhanced Building Types**: Added multi-story building options (3-5 floors, 6-10 floors, 11-15 floors, industrial warehouses, commercial centers)
- **Location Autocomplete**: Implemented Argentine location autocomplete with province detection and cost factor calculation
- **Database Compatibility**: Fixed PostgreSQL Decimal type conversions for monetary fields
- **Smart Cost Calculation**: Location-based pricing adjustments (CABA +30%, Buenos Aires +10%, etc.)
- **Automated Project Creation**: Complete project setup with stages, tasks, budgets, and AI recommendations
- **User Experience**: Improved form validation and real-time location suggestions

### Technical Improvements
- **Authentication Architecture**: main_app.py with Authlib OAuth2 configuration
- **Database Schema**: Enhanced Usuario model with OAuth support and organization relationships
- **Security**: Werkzeug password hashing and session management
- **User Experience**: Auto-detection of OAuth availability with informative messages
- **Template Updates**: Consistent auth forms with Bootstrap styling
- **PostgreSQL Integration**: Full migration to PostgreSQL with proper foreign key relationships
- **Multi-Tenant Database Design**: All core tables include organizacion_id for data isolation
- Decimal type conversion for all monetary database fields
- Enhanced error handling for PostgreSQL data types
- Location-based cost factor detection from autocomplete
- Comprehensive building type configurations with specific industrial workflows