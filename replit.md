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

### Presupuestos Module Redesign (29 July 2025)
- **Menu Simplification**: Removed "Nuevo Presupuesto" from dropdown menu - now only "Ver Presupuestos" option
- **Comprehensive Form Redesign**: Complete overhaul of presupuesto creation form with:
  - **New Required Fields**: Nombre obra, tipo obra (Casa 1/2 plantas, Edificio 3-5/5-10 pisos), ubicación, tipo construcción (Económica/Estándar/Premium), superficie m²
  - **Optional Enhancement Fields**: Fechas inicio/fin, presupuesto disponible (ARS/USD), cliente, plano PDF drag-and-drop
  - **Removed Fields**: Observaciones editables, IVA editable (fixed at 21%)
  - **IA Integration**: Direct "Calcular con IA" button in form with real-time results panel
- **Automatic Work Creation**: Form now creates both obra and presupuesto simultaneously from single interface
- **Modern UX**: Drag-and-drop PDF upload, responsive layout with guidance panels, real-time validation
- **Backend Integration**: Complete form processing with automatic obra generation and presupuesto association

### Menu Optimization and Corporate Branding (Latest Update)
- **Complete Removal of Asistente IA Menu**: Eliminated entire "Asistente IA" dropdown from main navigation for cleaner interface
- **Relocated Super Admin Access**: Moved "Auditoría IA (Super Admin)" to user dropdown menu (top-right) for authorized users only
- **Role-Based Menu Access**: Super admin features now properly segregated in user profile menu with email-based authentication
- **Streamlined Main Navigation**: Focused navigation on core operational modules (Obras, Presupuestos, Equipos, etc.)
- **Corporate Landing Page**: Professional INICIO page with glassmorphism design using provided architectural background image

## Recent Changes (July 2025)

### Mapa Interactivo - Estado Actual (21 Julio 2025)
- **Problema Persistente**: Mapa de Leaflet presenta fragmentación visual y renderizado incorrecto
- **Intentos realizados**: Múltiples implementaciones con diferentes enfoques CSS y JavaScript
- **Funcionalidad parcial**: Backend de obras con coordenadas funcional, API Open-Meteo integrada
- **Panel clima**: Implementado pero no se activa por problemas del mapa
- **Estado**: Requiere enfoque alternativo o biblioteca diferente (ej: Google Maps, Mapbox)
- **Logs técnicos**: Mapa se inicializa correctamente en consola pero falla renderizado visual

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

## Latest Updates (August 2025)

### Complete Construction Roles System Implementation (15 August 2025)
- **Comprehensive Role Hierarchy**: Implemented 30+ specific construction roles organized in 5 hierarchical categories:
  - Dirección y gestión (Director General, Gerente Técnico, etc.)
  - Técnico-ingeniería (Arquitecto, Ingeniero, Maestro Mayor, etc.) 
  - Supervisión y control (Jefe de Obra, Supervisor, Capataz, etc.)
  - Administración y soporte (Administrativo, Seguridad, etc.)
  - Operativo en terreno (Oficiales, Ayudantes, Operadores, etc.)
- **Enhanced Authentication Forms**: Updated all registration and user assignment forms with organized role dropdowns
- **Custom Jinja2 Filter**: Created `obtener_nombre_rol` filter for converting role codes to readable names
- **Obras Assignment Modal**: Updated obra assignment modal with complete role selection
- **Database Integration**: All roles properly integrated with existing permission system

### Predefined Tasks System Completion (15 August 2025)
- **Complete Task Database**: Implemented comprehensive task definitions for all 13 construction stages
- **Unified Data Format**: Standardized all tasks with nombre, descripcion, and horas fields
- **Error Resolution**: Fixed "string indices must be integers" error in seed_tareas_para_etapa function
- **Enhanced Frontend**: Improved Nueva Tarea modal with automatic task suggestions and selection
- **Smart Placeholders**: Dynamic placeholder text showing first available task for each stage
- **Idempotent Creation**: Tasks are created automatically when stages are added, preventing duplicates

### Marketplaces Module Implementation (15 August 2025)
- **Complete Marketplace System**: Full-featured provider search and quotation management system
- **Provider Database Models**: Proveedor, CategoriaProveedor, SolicitudCotizacion models with organization isolation
- **Search Functionality**: Advanced search with category, location, rating, and keyword filters
- **Real-time API**: JSON API for provider search with AJAX frontend integration
- **Quotation Management**: Request and track quotations with status workflow (pending, quoted, accepted, rejected)
- **Category Organization**: Structured categories (materials, equipment, services, professionals) with subcategories
- **Sample Data**: 10 example providers across all categories with realistic Argentine business data
- **Dashboard Integration**: Marketplace button added to main dashboard actions panel
- **Permission System**: Role-based access for all construction roles (administrators, technicians, operators)

### Technical Improvements
- **Data Consistency**: All predefined tasks now use consistent dictionary format with full metadata
- **Error Handling**: Robust error handling for both string and dictionary task formats
- **Frontend Enhancement**: Improved JavaScript with proper null checking and field clearing
- **Role Integration**: Complete integration of construction roles throughout the application
- **Marketplace Architecture**: Complete blueprint-based module with templates, API endpoints, and database integration