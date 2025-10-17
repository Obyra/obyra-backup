# OBYRA IA - Construction Management Platform

## Overview
OBYRA IA is a comprehensive web platform for construction companies, architects, and firms in Argentina and Latin America. It automates project management, team coordination, budgeting, and construction documentation, aiming to manage the complete construction workflow. The platform provides a modular architecture built with Flask and SQLAlchemy. Its business vision is to streamline construction operations, enhance efficiency, and provide robust tools for project oversight and financial management in the construction sector.

## Database migrations
After pulling the latest changes, run:

```
flask db upgrade
```

This command applies the lightweight migrations (incluyendo las columnas de estado y vigencia de presupuestos) contra tu base local antes de lanzar la app.

> **Importante:** exportá `ALEMBIC_RUNNING=1` y `FLASK_SKIP_CREATE_ALL=1` cuando ejecutes migraciones o scripts que importan `app.py` sin levantar la aplicación. Esto evita que SQLAlchemy intente crear tablas fuera del flujo de Alembic.

Para inicializar el catálogo global de inventario podés usar el nuevo comando CLI:

```
flask seed:inventario --global
```

También acepta múltiples `--org <identificador>` para sembrar organizaciones puntuales.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture
### Core Design Principles
The platform adopts a modular, blueprint-based architecture built on Flask, emphasizing scalability, maintainability, and clear separation of concerns. UI/UX decisions prioritize a responsive, modern design with a construction industry theme.

### Frontend Architecture
- **Technology Stack**: Flask with Jinja2 templating, Bootstrap 5 for responsive design.
- **Interactivity**: Vanilla JavaScript with Chart.js for data visualization.
- **Styling & Icons**: Custom CSS for thematic consistency, Font Awesome for iconography.
- **Key UI/UX Elements**:
    - Glassmorphism design on the corporate landing page.
    - Responsive forms with real-time validation and guidance panels.
    - Drag-and-drop functionality for file uploads (e.g., PDF plans).
    - Streamlined main navigation, focusing on core operational modules.

### Backend Architecture
- **Framework**: Flask (Python).
- **ORM**: SQLAlchemy with Flask-SQLAlchemy for database interactions.
- **Authentication**: Flask-Login for session management, Werkzeug for password hashing.
- **Application Structure**: Blueprint-based modularity for features like Project Management, Budgeting, Team, Inventory, and Marketplaces.
- **Security**: Role-based access control, CSRF protection, secure session management.

### Database Architecture
- **Primary Database**: SQLite for development, PostgreSQL recommended for production.
- **ORM**: SQLAlchemy declarative base model.
- **Connection Management**: Configured with connection pooling and pre-ping.
- **Data Model**: Includes modules for User Management, Projects (Obras), Budgets (Presupuestos), Inventory (Inventario), Time Tracking, Organizations, Providers, Quotation Requests, and Advanced Task Management with member assignments and progress tracking.
- **Multi-Tenancy**: Organization-based multi-tenancy with data isolation (`organizacion_id` in core tables).
- **Data Types**: Consistent use of Decimal types for monetary fields.

### Core System Features & Design Decisions
- **Authentication System**:
    - Manual registration and Google OAuth2 integration with automatic profile creation and picture sync.
    - Role-based access control (Administrator, Technician, Operator) with 30+ specific construction roles.
    - Administrative user registration.
- **Project Management (Obras)**:
    - Comprehensive project lifecycle management with status tracking.
    - Enhanced building types (single-family, multi-story, industrial, commercial).
    - Argentine location autocomplete with cost factor calculation.
    - Automated project and budget creation from a single interface.
- **Budget Management (Presupuestos)**:
    - Detailed budget creation with PDF generation (ReportLab).
    - Fixed VAT calculation (21%).
    - "Calcular con IA" integration for real-time budget estimations.
- **Team Management (Equipos)**:
    - User profile and performance tracking.
    - Role-based dashboard access.
    - Integrated time tracking.
- **Inventory Control (Inventario)**:
    - Tracking of materials, tools, and machinery.
    - Stock level monitoring with alerts.
- **Reporting System (Reportes)**:
    - Comprehensive dashboard with KPIs and date-range filtering.
- **Organization-Based Multi-Tenancy**:
    - Users grouped by organizations with data isolation.
    - Invitation system for user onboarding to organizations.
- **Intelligent Project Configuration**:
    - Location-based pricing adjustments.
    - Automated project setup with stages, tasks, and AI recommendations.
- **Advanced Task Management System**:
    - Comprehensive task definitions for 13 construction stages.
    - Automatic task creation when stages are added, with smart suggestions.
    - Multi-user task assignment with quotas and progress tracking.
    - Bulk operations for task assignment and management.
    - Real-time progress tracking with photo uploads and quantity metrics.
    - Individual "Mis Tareas" dashboard for user-specific task management.
    - Visual progress indicators with completion percentages and metrics.
    - Task completion workflows with automated status updates.
- **OBYRA Market - Comprehensive B2B Marketplace**:
    - Complete ML-like B2B marketplace with seller masking until payment confirmation.
    - Multi-seller cart and checkout system with automated purchase order generation.
    - MercadoPago payment integration with webhook-based order confirmation.
    - Commission system by category and exposure level (classic/premium).
    - Q&A system for products with seller notifications.
    - Comprehensive product catalog with variants, images, and specifications.
    - PDF purchase order generation using ReportLab with email notifications.
    - Role-based access (buyers, sellers, backoffice admin).
- **OBYRA Marketplace - Complete B2B ML-like Implementation**:
    - Isolated module in marketplace/ directory with mk_ prefixed tables
    - Complete seller masking in public endpoints (shows "OBYRA Partner")
    - Real seller information revealed only in cart/checkout/orders for authenticated users
    - Commission calculation system with category-based rates
    - PDF purchase order generation using ReportLab with automatic email notifications
    - MercadoPago webhook integration for payment processing
    - Multi-seller cart and checkout with automatic PO generation per seller
    - Complete API contract implementation following ML specifications
- **Interactive Map (Ongoing)**:
    - Integration attempts with Leaflet for project location visualization, currently facing rendering issues. Backend for coordinates and Open-Meteo API for weather data is functional.

## External Dependencies
### Python Packages
- **Flask**: Web application framework.
- **Flask-SQLAlchemy**: ORM integration.
- **Flask-Login**: User session management.
- **Werkzeug**: Security utilities (password hashing).
- **ReportLab**: PDF generation.
- **Authlib**: OAuth2 integration (for Google OAuth).

### Frontend Libraries
- **Bootstrap 5**: CSS framework for responsive design.
- **Font Awesome**: Icon library.
- **Chart.js**: JavaScript charting library.
- **Leaflet**: (Attempted) JavaScript library for interactive maps.

### Databases & Tools
- **SQLite**: Development database.
- **PostgreSQL**: Recommended production database.
- **Jinja2**: Template engine (included with Flask).