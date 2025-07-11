// OBYRA IA - JavaScript principal para funcionalidades del sistema

document.addEventListener('DOMContentLoaded', function() {
    // Inicializar componentes
    initializeTooltips();
    initializeAutoSave();
    initializeSearchFilters();
    initializeFormValidations();
    initializeProgressAnimations();
    initializeNotifications();
    initializeConstructionFeatures();
});

// Inicializar tooltips de Bootstrap
function initializeTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

// Sistema de autoguardado para formularios largos
function initializeAutoSave() {
    const forms = document.querySelectorAll('form[data-autosave]');
    
    forms.forEach(form => {
        const formId = form.id || 'form_' + Date.now();
        const saveKey = 'obyra_autosave_' + formId;
        
        // Cargar datos guardados
        loadFormData(form, saveKey);
        
        // Guardar cambios automáticamente
        form.addEventListener('input', debounce(function() {
            saveFormData(form, saveKey);
            showAutoSaveIndicator();
        }, 1000));
        
        // Limpiar al enviar exitosamente
        form.addEventListener('submit', function() {
            localStorage.removeItem(saveKey);
        });
    });
}

// Filtros de búsqueda en tiempo real
function initializeSearchFilters() {
    const searchInputs = document.querySelectorAll('[data-search-target]');
    
    searchInputs.forEach(input => {
        const targetSelector = input.dataset.searchTarget;
        const searchDelay = parseInt(input.dataset.searchDelay) || 300;
        
        input.addEventListener('input', debounce(function() {
            filterElements(targetSelector, this.value);
        }, searchDelay));
    });
}

// Validaciones de formulario específicas para construcción
function initializeFormValidations() {
    // Validación de fechas de obra
    const fechaInicioInputs = document.querySelectorAll('input[name="fecha_inicio"]');
    const fechaFinInputs = document.querySelectorAll('input[name="fecha_fin_estimada"]');
    
    fechaInicioInputs.forEach(input => {
        input.addEventListener('change', function() {
            validateProjectDates(this);
        });
    });
    
    fechaFinInputs.forEach(input => {
        input.addEventListener('change', function() {
            validateProjectDates(this);
        });
    });
    
    // Validación de presupuestos
    const presupuestoInputs = document.querySelectorAll('input[type="number"][name*="precio"], input[type="number"][name*="cantidad"]');
    presupuestoInputs.forEach(input => {
        input.addEventListener('input', function() {
            calculateBudgetTotals(this);
        });
    });
    
    // Validación de stock de inventario
    const stockInputs = document.querySelectorAll('input[name*="stock"]');
    stockInputs.forEach(input => {
        input.addEventListener('input', function() {
            validateStock(this);
        });
    });
}

// Animaciones de progreso
function initializeProgressAnimations() {
    const progressBars = document.querySelectorAll('.progress-bar');
    
    // Observador de intersección para animar cuando sea visible
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const progressBar = entry.target;
                const progress = progressBar.style.width;
                progressBar.style.width = '0%';
                
                setTimeout(() => {
                    progressBar.style.width = progress;
                    progressBar.style.transition = 'width 1.5s ease-in-out';
                }, 100);
                
                observer.unobserve(progressBar);
            }
        });
    });
    
    progressBars.forEach(bar => observer.observe(bar));
}

// Sistema de notificaciones
function initializeNotifications() {
    // Auto-ocultar alertas después de 5 segundos
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    alerts.forEach(alert => {
        setTimeout(() => {
            if (alert.classList.contains('show')) {
                bootstrap.Alert.getOrCreateInstance(alert).close();
            }
        }, 5000);
    });
    
    // Notificaciones de stock bajo
    checkLowStockItems();
    
    // Notificaciones de obras próximas a vencer
    checkUpcomingDeadlines();
}

// Funcionalidades específicas de construcción
function initializeConstructionFeatures() {
    // Calculadora de materiales
    initializeMaterialCalculator();
    
    // Convertidor de unidades
    initializeUnitConverter();
    
    // Validador de códigos de construcción argentinos
    initializeArgentineValidations();
    
    // Clima para obras (si está disponible)
    initializeWeatherWidget();
}

// Funciones auxiliares

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function saveFormData(form, key) {
    const formData = new FormData(form);
    const data = {};
    
    for (let [name, value] of formData.entries()) {
        data[name] = value;
    }
    
    localStorage.setItem(key, JSON.stringify(data));
}

function loadFormData(form, key) {
    const savedData = localStorage.getItem(key);
    if (savedData) {
        const data = JSON.parse(savedData);
        
        Object.entries(data).forEach(([name, value]) => {
            const input = form.querySelector(`[name="${name}"]`);
            if (input) {
                input.value = value;
            }
        });
    }
}

function showAutoSaveIndicator() {
    // Crear o mostrar indicador de guardado automático
    let indicator = document.getElementById('autosave-indicator');
    if (!indicator) {
        indicator = document.createElement('div');
        indicator.id = 'autosave-indicator';
        indicator.className = 'position-fixed bottom-0 end-0 m-3 alert alert-success p-2';
        indicator.innerHTML = '<i class="fas fa-save me-1"></i>Guardado automáticamente';
        indicator.style.zIndex = '9999';
        document.body.appendChild(indicator);
    }
    
    indicator.style.display = 'block';
    setTimeout(() => {
        indicator.style.display = 'none';
    }, 2000);
}

function filterElements(targetSelector, searchTerm) {
    const elements = document.querySelectorAll(targetSelector);
    const term = searchTerm.toLowerCase();
    
    elements.forEach(element => {
        const text = element.textContent.toLowerCase();
        const matches = text.includes(term);
        
        element.style.display = matches ? '' : 'none';
        
        if (matches && term) {
            highlightSearchTerm(element, term);
        } else {
            removeHighlight(element);
        }
    });
}

function highlightSearchTerm(element, term) {
    const walker = document.createTreeWalker(
        element,
        NodeFilter.SHOW_TEXT,
        null,
        false
    );
    
    const textNodes = [];
    let node;
    
    while (node = walker.nextNode()) {
        if (node.textContent.toLowerCase().includes(term)) {
            textNodes.push(node);
        }
    }
    
    textNodes.forEach(textNode => {
        const parent = textNode.parentNode;
        const text = textNode.textContent;
        const regex = new RegExp(`(${term})`, 'gi');
        const highlightedText = text.replace(regex, '<span class="search-highlight">$1</span>');
        
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = highlightedText;
        
        while (tempDiv.firstChild) {
            parent.insertBefore(tempDiv.firstChild, textNode);
        }
        
        parent.removeChild(textNode);
    });
}

function removeHighlight(element) {
    const highlights = element.querySelectorAll('.search-highlight');
    highlights.forEach(highlight => {
        const parent = highlight.parentNode;
        parent.replaceChild(document.createTextNode(highlight.textContent), highlight);
    });
}

function validateProjectDates(input) {
    const form = input.closest('form');
    const fechaInicio = form.querySelector('input[name="fecha_inicio"]');
    const fechaFin = form.querySelector('input[name="fecha_fin_estimada"]');
    
    if (fechaInicio && fechaFin && fechaInicio.value && fechaFin.value) {
        const inicio = new Date(fechaInicio.value);
        const fin = new Date(fechaFin.value);
        
        if (fin <= inicio) {
            fechaFin.setCustomValidity('La fecha de fin debe ser posterior a la fecha de inicio');
            showValidationMessage(fechaFin, 'La fecha de fin debe ser posterior a la fecha de inicio');
        } else {
            fechaFin.setCustomValidity('');
            hideValidationMessage(fechaFin);
            
            // Calcular duración del proyecto
            const diffTime = Math.abs(fin - inicio);
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
            showProjectDuration(form, diffDays);
        }
    }
}

function calculateBudgetTotals(input) {
    const row = input.closest('tr') || input.closest('.budget-row');
    if (!row) return;
    
    const cantidadInput = row.querySelector('input[name*="cantidad"]');
    const precioInput = row.querySelector('input[name*="precio"]');
    const totalElement = row.querySelector('.total-amount');
    
    if (cantidadInput && precioInput && totalElement) {
        const cantidad = parseFloat(cantidadInput.value) || 0;
        const precio = parseFloat(precioInput.value) || 0;
        const total = cantidad * precio;
        
        totalElement.textContent = formatCurrency(total);
        
        // Actualizar totales generales
        updateBudgetGrandTotal();
    }
}

function validateStock(input) {
    const stockActual = parseFloat(input.value) || 0;
    const stockMinimo = parseFloat(input.dataset.stockMinimo) || 0;
    
    const row = input.closest('tr') || input.closest('.card');
    
    if (stockActual <= stockMinimo) {
        row.classList.add('stock-critico');
        row.classList.remove('stock-normal', 'stock-bajo');
        showStockAlert(input, 'crítico');
    } else if (stockActual <= stockMinimo * 1.2) {
        row.classList.add('stock-bajo');
        row.classList.remove('stock-normal', 'stock-critico');
        showStockAlert(input, 'bajo');
    } else {
        row.classList.add('stock-normal');
        row.classList.remove('stock-critico', 'stock-bajo');
        hideStockAlert(input);
    }
}

function checkLowStockItems() {
    // Esta función se puede conectar con una API para verificar stock bajo
    const stockItems = document.querySelectorAll('[data-stock-level]');
    
    stockItems.forEach(item => {
        const level = item.dataset.stockLevel;
        if (level === 'low' || level === 'critical') {
            showNotification('Stock bajo detectado', 'warning');
        }
    });
}

function checkUpcomingDeadlines() {
    // Verificar obras próximas a vencer
    const deadlineItems = document.querySelectorAll('[data-deadline]');
    const today = new Date();
    const weekFromNow = new Date(today.getTime() + 7 * 24 * 60 * 60 * 1000);
    
    deadlineItems.forEach(item => {
        const deadline = new Date(item.dataset.deadline);
        if (deadline <= weekFromNow && deadline > today) {
            const daysLeft = Math.ceil((deadline - today) / (1000 * 60 * 60 * 24));
            showNotification(`Obra vence en ${daysLeft} días`, 'warning');
        }
    });
}

function initializeMaterialCalculator() {
    const calculatorButtons = document.querySelectorAll('[data-calculate-material]');
    
    calculatorButtons.forEach(button => {
        button.addEventListener('click', function() {
            const materialType = this.dataset.calculateMaterial;
            showMaterialCalculator(materialType);
        });
    });
}

function initializeUnitConverter() {
    const converterInputs = document.querySelectorAll('[data-unit-convert]');
    
    converterInputs.forEach(input => {
        input.addEventListener('input', function() {
            const fromUnit = this.dataset.unitConvert;
            const toUnit = this.dataset.unitTarget;
            const value = parseFloat(this.value) || 0;
            
            const converted = convertUnits(value, fromUnit, toUnit);
            const targetInput = document.querySelector(`input[name="${this.dataset.targetInput}"]`);
            
            if (targetInput) {
                targetInput.value = converted.toFixed(3);
            }
        });
    });
}

function initializeArgentineValidations() {
    // Validación de CUIT argentino
    const cuitInputs = document.querySelectorAll('input[data-validate="cuit"]');
    cuitInputs.forEach(input => {
        input.addEventListener('blur', function() {
            if (this.value && !validateCUIT(this.value)) {
                this.setCustomValidity('CUIT inválido');
                showValidationMessage(this, 'El CUIT ingresado no es válido');
            } else {
                this.setCustomValidity('');
                hideValidationMessage(this);
            }
        });
    });
    
    // Formato de teléfonos argentinos
    const phoneInputs = document.querySelectorAll('input[data-validate="phone-ar"]');
    phoneInputs.forEach(input => {
        input.addEventListener('input', function() {
            this.value = formatArgentinePhone(this.value);
        });
    });
}

function initializeWeatherWidget() {
    const weatherWidget = document.getElementById('weather-widget');
    if (weatherWidget) {
        const lat = weatherWidget.dataset.lat;
        const lon = weatherWidget.dataset.lon;
        
        if (lat && lon) {
            fetchWeatherData(lat, lon);
        }
    }
}

// Funciones de utilidad

function formatCurrency(amount) {
    return new Intl.NumberFormat('es-AR', {
        style: 'currency',
        currency: 'ARS'
    }).format(amount);
}

function convertUnits(value, fromUnit, toUnit) {
    // Tabla de conversiones para construcción
    const conversions = {
        'metro_metro2': (v, width = 1) => v * width,
        'metro2_metro3': (v, height = 1) => v * height,
        'kilogramo_tonelada': v => v / 1000,
        'tonelada_kilogramo': v => v * 1000,
        'litro_metro3': v => v / 1000,
        'metro3_litro': v => v * 1000
    };
    
    const conversionKey = `${fromUnit}_${toUnit}`;
    const converter = conversions[conversionKey];
    
    return converter ? converter(value) : value;
}

function validateCUIT(cuit) {
    // Validación simplificada de CUIT argentino
    const cleanCuit = cuit.replace(/[-\s]/g, '');
    
    if (cleanCuit.length !== 11 || !/^\d+$/.test(cleanCuit)) {
        return false;
    }
    
    const multipliers = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2];
    let sum = 0;
    
    for (let i = 0; i < 10; i++) {
        sum += parseInt(cleanCuit[i]) * multipliers[i];
    }
    
    const remainder = sum % 11;
    const checkDigit = remainder < 2 ? remainder : 11 - remainder;
    
    return parseInt(cleanCuit[10]) === checkDigit;
}

function formatArgentinePhone(phone) {
    // Formateo básico para teléfonos argentinos
    let cleaned = phone.replace(/\D/g, '');
    
    if (cleaned.startsWith('54')) {
        cleaned = cleaned.substring(2);
    }
    
    if (cleaned.length === 10) {
        return cleaned.replace(/(\d{2})(\d{4})(\d{4})/, '$1 $2-$3');
    } else if (cleaned.length === 8) {
        return cleaned.replace(/(\d{4})(\d{4})/, '$1-$2');
    }
    
    return phone;
}

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `alert alert-${type} position-fixed top-0 end-0 m-3`;
    notification.style.zIndex = '9999';
    notification.innerHTML = `
        <div class="d-flex align-items-center">
            <i class="fas fa-${getIconForType(type)} me-2"></i>
            ${message}
            <button type="button" class="btn-close ms-auto" data-bs-dismiss="alert"></button>
        </div>
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        if (notification.parentNode) {
            notification.parentNode.removeChild(notification);
        }
    }, 5000);
}

function getIconForType(type) {
    const icons = {
        'success': 'check-circle',
        'warning': 'exclamation-triangle',
        'danger': 'times-circle',
        'info': 'info-circle'
    };
    return icons[type] || 'info-circle';
}

function showValidationMessage(input, message) {
    hideValidationMessage(input);
    
    const feedback = document.createElement('div');
    feedback.className = 'invalid-feedback d-block';
    feedback.textContent = message;
    feedback.setAttribute('data-validation-for', input.name);
    
    input.parentNode.appendChild(feedback);
    input.classList.add('is-invalid');
}

function hideValidationMessage(input) {
    const existingFeedback = input.parentNode.querySelector(`[data-validation-for="${input.name}"]`);
    if (existingFeedback) {
        existingFeedback.remove();
    }
    input.classList.remove('is-invalid');
}

function showProjectDuration(form, days) {
    let durationDisplay = form.querySelector('.project-duration');
    
    if (!durationDisplay) {
        durationDisplay = document.createElement('div');
        durationDisplay.className = 'project-duration alert alert-info mt-2';
        form.appendChild(durationDisplay);
    }
    
    const weeks = Math.floor(days / 7);
    const remainingDays = days % 7;
    let durationText = `Duración estimada: ${days} días`;
    
    if (weeks > 0) {
        durationText += ` (${weeks} semanas`;
        if (remainingDays > 0) {
            durationText += ` y ${remainingDays} días`;
        }
        durationText += ')';
    }
    
    durationDisplay.innerHTML = `<i class="fas fa-calendar-alt me-2"></i>${durationText}`;
}

function updateBudgetGrandTotal() {
    const totalElements = document.querySelectorAll('.total-amount');
    let grandTotal = 0;
    
    totalElements.forEach(element => {
        const amount = parseFloat(element.textContent.replace(/[^\d.-]/g, '')) || 0;
        grandTotal += amount;
    });
    
    const grandTotalElement = document.querySelector('.grand-total');
    if (grandTotalElement) {
        grandTotalElement.textContent = formatCurrency(grandTotal);
    }
}

function showStockAlert(input, level) {
    const alertId = `stock-alert-${input.name}`;
    let alert = document.getElementById(alertId);
    
    if (!alert) {
        alert = document.createElement('div');
        alert.id = alertId;
        alert.className = `alert alert-${level === 'crítico' ? 'danger' : 'warning'} mt-1`;
        input.parentNode.appendChild(alert);
    }
    
    alert.innerHTML = `<i class="fas fa-exclamation-triangle me-1"></i>Stock ${level}`;
}

function hideStockAlert(input) {
    const alertId = `stock-alert-${input.name}`;
    const alert = document.getElementById(alertId);
    if (alert) {
        alert.remove();
    }
}

function showMaterialCalculator(materialType) {
    // Implementar calculadora específica según el tipo de material
    console.log(`Calculadora para ${materialType} - Función a implementar`);
}

function fetchWeatherData(lat, lon) {
    // Implementar llamada a API de clima
    console.log(`Obtener clima para lat: ${lat}, lon: ${lon} - Función a implementar`);
}

// Exportar funciones para uso global
window.ObyriaIA = {
    formatCurrency,
    validateCUIT,
    showNotification,
    convertUnits,
    formatArgentinePhone
};
