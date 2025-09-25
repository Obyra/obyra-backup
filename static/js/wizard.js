anel al cargar
        updateTaskSelectionPanel();
        console.log('✅ WIZARD: Event listeners de tareas rebindeados');
      }, 50);
      
      console.log(`🎯 WIZARD: HTML renderizado en contenedor:`, { 
        contenedor: list.id || 'sin-id', 
        tareasCount: tareas.length,
        htmlLength: html.length,
        hasActive: list.classList.contains('active'),
        hasShow: list.classList.contains('show'),
        noDNone: !list.classList.contains('d-none'),
        isActuallyVisible: !!(list.offsetParent),
        ariaHidden: list.getAttribute('aria-hidden')
      });
      console.log(`🎯 WIZARD: Contenedor después del render:`, list.innerHTML.substring(0, 200) + '...');
    } else {
      console.error('❌ WIZARD: No se encontró contenedor para renderizar tareas');
    }
    
    console.log(`✅ WIZARD: ${tareas.length} plantillas del catálogo cargadas exitosamente`);
    
  } catch (error) {
    console.error('❌ WIZARD: Error cargando plantillas del catálogo:', error);
    if (spin) spin.classList.add('d-none');
    if (list) {
      list.innerHTML = `<div class="alert alert-warning">
        <h6>No se pudieron cargar las plantillas</h6>
        <p class="mb-0">Error: ${error.message}</p>
        <button class="btn btn-sm btn-outline-primary mt-2" onclick="window.loadTareasWizard(${obraId}, ${JSON.stringify(slugs)})">
          <i class="fas fa-refresh me-1"></i>Reintentar
        </button>
      </div>`;
    }
  }
};

// =================== NAVEGACIÓN PASO 1 → 2 y PASO 2 → 3 ===================
// Interceptor único para botón "Siguiente" 
function setupUniqueInterceptor() {
  const btnSiguiente = document.getElementById('wizardBtnSiguiente');
  if (!btnSiguiente) {
    console.error('❌ WIZARD: botón wizardBtnSiguiente no encontrado');
    return;
  }
  if (btnSiguiente.dataset.wizardBound) {
    console.log('🔥 WIZARD: setupUniqueInterceptor ya ejecutado, saltando');
    return;
  }
  
  console.log('🔥 WIZARD: Configurando interceptor para botón Siguiente');
  btnSiguiente.dataset.wizardBound = 'true';
  
  btnSiguiente.addEventListener('click', (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    ev.stopImmediatePropagation?.();
    
    console.log('🔥 WIZARD: Click en botón Siguiente detectado');
    
    // Determinar paso actual usando Bootstrap tab-pane classes
    const modal = document.getElementById('wizardTareasModal');
    const paso1Visible = modal.querySelector('#wizardStep1.active, #paso1.active, .tab-pane.active[id*="1"]');
    const paso2Visible = modal.querySelector('#wizardStep2.active, #paso2.active, .tab-pane.active[id*="2"]');
    
    // Debug: mostrar todos los pasos y sus clases
    const allSteps = modal.querySelectorAll('[id*="wizardStep"], [id*="paso"]');
    console.log('🔍 WIZARD: Todos los pasos encontrados:', Array.from(allSteps).map(el => ({
      id: el.id,
      classes: el.className,
      hasActive: el.classList.contains('active'),
      hasShow: el.classList.contains('show')
    })));
    
    // Fallback: usar estado global si está disponible
    const currentStep = window.WZ_STATE?.currentStep || window.currentStep || 1;
    
    console.log(`🔍 WIZARD: Detectando paso - Paso1Visible: ${!!paso1Visible}, Paso2Visible: ${!!paso2Visible}, currentStep: ${currentStep}`);
    
    if (paso1Visible || currentStep === 1) {
      // PASO 1 → 2: Validar etapas seleccionadas usando Set
      const etapasSeleccionadas = window.WZ_STATE?.etapasSel?.size || 0;
      if (etapasSeleccionadas === 0) {
        alert('Debe seleccionar al menos una etapa');
        return;
      }
      
      console.log('🔥 WIZARD: Navegando Paso 1 → 2');
      window.WZ_STATE = window.WZ_STATE || {};
      window.WZ_STATE.currentStep = 2;
      window.gotoPaso?.(2);
      
      // 🎯 CARGAR TAREAS DEL CATÁLOGO para las etapas seleccionadas (usando Set)
      setTimeout(() => {
        const etapaIds = getSelectedEtapaIds();
        // Convertir IDs a slugs - buscar en DOM solo los slugs, no el estado checked
        const slugs = etapaIds.map(id => {
          const cb = document.querySelector(`.etapa-checkbox[data-etapa-id="${id}"]`);
          return cb?.getAttribute('data-slug') || cb?.value || id;
        }).filter(Boolean);
        
        console.log(`🔥 WIZARD: Cargando tareas para etapas:`, slugs);
        
        // Obtener obra ID
        let obraId = document.getElementById('wizardTareasModal')?.getAttribute('data-obra-id') || window.obraId;
        
        if (obraId && slugs.length > 0 && typeof window.loadTareasWizard === 'function') {
          window.loadTareasWizard(obraId, slugs);
        } else {
          console.error('❌ WIZARD: No se puede cargar tareas - obraId:', obraId, 'slugs:', slugs);
        }
      }, 100);
      
    } else if (paso2Visible || currentStep === 2) {
      // PASO 2 → 3: Capturar tareas seleccionadas del catálogo
      console.log(`🔍 WIZARD: Iniciando captura Paso 2 → 3`);
      
      // 🎯 DEBUG: No contar DOM checkboxes, usar información de estado
      console.log(`🔍 WIZARD: Estado actual:`, {
        etapasEnSet: window.WZ_STATE?.etapasSel?.size || 0,
        mensaje: 'Debug migrado a Set-based approach'
      });
      
      // 🎯 DEBUG REMOVED: Ya no usar todosCheckboxes ni tareasSeleccionadas del DOM
      
      // 🎯 VALIDATION: Usar estado de tareas seleccionadas - defer to Paso 3 validation
      // tareasSeleccionadas no está disponible como DOM collection aquí
      console.log('🔍 WIZARD: Validación de tareas diferida al Paso 3');
      
      // 🎯 CAPTURAR TAREAS EN WZ_STATE.tareasSel
      window.WZ_STATE = window.WZ_STATE || {};
      window.WZ_STATE.tareasSel = [];
      
      // 🎯 COLLECT TASKS: Buscar tareas checked en DOM, pero no depender del estado checked
      document.querySelectorAll('.tarea-checkbox:checked:not(:disabled)').forEach(checkbox => {
        const tareaData = {
          id: checkbox.getAttribute('data-id') || '',
          nombre: checkbox.getAttribute('data-nombre') || checkbox.nextElementSibling?.textContent?.trim() || 'Tarea sin nombre',
          etapa_slug: checkbox.getAttribute('data-etapa') || '',
          descripcion: checkbox.getAttribute('data-descripcion') || '',
          horas: checkbox.getAttribute('data-horas') || '8'
        };
        window.WZ_STATE.tareasSel.push(tareaData);
      });
      
      console.log(`🎯 WIZARD: ${window.WZ_STATE.tareasSel.length} tareas capturadas del catálogo:`, window.WZ_STATE.tareasSel);
      
      // Navegar al Paso 3 y popularlo
      console.log('🔥 WIZARD: Navegando Paso 2 → 3');
      window.WZ_STATE.currentStep = 3;
      window.gotoPaso?.(3);
      
      // Poblar el Paso 3 con las tareas seleccionadas
      setTimeout(() => {
        if (typeof window.populatePaso3 === 'function') {
          window.populatePaso3();
        }
      }, 100);
      
    } else if (currentStep === 3) {
      // PASO 3: Cambiar botón a "Confirmar" y preparar finalización
      console.log('🔍 WIZARD: Detectando Paso 3 - cambiando botón a Confirmar');
      
      // Validar que los campos requeridos estén completos
      const modal = document.getElementById('wizardTareasModal');
      const requiredFields = modal.querySelectorAll('#wizardStep3 input[required], #wizardStep3 select[required]');
      let hasEmptyRequired = false;
      
      requiredFields.forEach(field => {
        if (!field.value.trim()) {
          hasEmptyRequired = true;
          field.style.borderColor = '#dc3545';
        } else {
          field.style.borderColor = '';
        }
      });
      
      if (hasEmptyRequired) {
        alert('Por favor completa todos los campos requeridos');
        return;
      }
      
      // Cambiar el botón a "Confirmar" y simular click
      const btnSiguiente = document.getElementById('wizardBtnSiguiente');
      const btnConfirmar = document.getElementById('wizardBtnConfirmar');
      
      if (btnSiguiente && btnConfirmar) {
        btnSiguiente.style.display = 'none';
        btnConfirmar.style.display = 'inline-block';
        
        // Simular click en Confirmar para activar el handler existente
        setTimeout(() => {
          btnConfirmar.click();
        }, 100);
      } else {
        console.error('❌ WIZARD: Botones Siguiente/Confirmar no encontrados');
      }
      
    } else {
      console.warn(`⚠️ WIZARD: Paso no reconocido - currentStep: ${currentStep}`);
    }
  }, { capture: true });  // 🎯 Usar capture para evitar conflictos con otros listeners
  
  console.log('✅ WIZARD: Interceptor Paso 1→2 y 2→3 configurado');
}

// =================== INICIALIZACIÓN ===================
// Modal shown event listener
document.addEventListener('shown.bs.modal', (ev) => {
  if (ev.target?.id === 'wizardTareasModal') {
    console.log('🔥 WIZARD: Modal mostrado, iniciando carga');
    
    // Configurar interceptor de navegación Paso 1 → 2
    setupUniqueInterceptor();
    
    // Cargar catálogo de etapas
    setTimeout(() => {
      if (typeof window.cargarCatalogoEtapas === 'function') {
        window.cargarCatalogoEtapas();
      }
    }, 100);
  }
});

console.log('✅ WIZARD: Sistema estabilizado cargado - Event delegation completo');

// =================== GUARDS ANTI-DUPLICADO ===================
// 🛡️ Mutex: Prevent multiple operations
window.withMutex = async function(key, operation) {
  if (window.WZ_STATE.mutexes.has(key)) {
    console.log(`🚫 MUTEX: Operation '${key}' already in progress`);
    return null;
  }
  
  try {
    window.WZ_STATE.mutexes.add(key);
    console.log(`🔒 MUTEX: Acquired '${key}'`);
    return await operation();
  } finally {
    window.WZ_STATE.mutexes.delete(key);
    console.log(`🔓 MUTEX: Released '${key}'`);
  }
};

// 🛡️ Button Guard: Prevent multiple clicks
window.withButtonGuard = function(buttonId, operation) {
  return window.withMutex(`button:${buttonId}`, async () => {
    const btn = document.getElementById(buttonId);
    if (!btn) return await operation();
    
    const originalText = btn.innerHTML;
    const originalDisabled = btn.disabled;
    
    try {
      btn.disabled = true;
      btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Procesando...';
      window.WZ_STATE.buttonStates.set(buttonId, {originalText, originalDisabled});
      
      return await operation();
    } finally {
      btn.innerHTML = originalText;
      btn.disabled = originalDisabled;
      window.WZ_STATE.buttonStates.delete(buttonId);
    }
  });
};

// 🛡️ Request Deduplication: Cache identical requests
window.withRequestCache = async function(url, options = {}, ttl = 5000) {
  const cacheKey = `${url}:${JSON.stringify(options)}`;
  const cached = window.WZ_STATE.requestCache.get(cacheKey);
  
  if (cached && Date.now() - cached.timestamp < ttl) {
    console.log(`📦 CACHE: Using cached response for ${url}`);
    return cached.data;
  }
  
  try {
    const response = await fetchJSON(url, options);
    window.WZ_STATE.requestCache.set(cacheKey, {
      data: response,
      timestamp: Date.now()
    });
    
    // Auto-cleanup after TTL
    setTimeout(() => {
      window.WZ_STATE.requestCache.delete(cacheKey);
    }, ttl);
    
    return response;
  } catch (error) {
    // Don't cache errors
    console.error(`❌ REQUEST: Failed ${url}:`, error);
    throw error;
  }
};

// 🛡️ Idempotency: Generate unique keys for operations
window.generateIdempotencyKey = function(operation, data = {}) {
  const timestamp = Date.now();
  const payload = JSON.stringify(data);
  const hash = btoa(`${operation}:${timestamp}:${payload}`).slice(0, 16);
  return `${operation}_${hash}`;
};

console.log('🛡️ GUARDS: Anti-duplicado system loaded');