/**
 * OBYRA IA - Wizard de Tareas
 * Sistema completo de creación de etapas y tareas en lote
 */

console.log('📦 Wizard.js cargado');

// Constantes globales
const PREF = '/obras';

// Funciones auxiliares
async function fetchJSON(url, opts) {
  try {
    const response = await fetch(url, opts);
    if (!response.ok) {
      if (response.headers.get('content-type')?.includes('application/json')) {
        const errorData = await response.json();
        throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
      } else {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
    }
    return await response.json();
  } catch (error) {
    console.error('❌ fetchJSON error:', error);
    throw error;
  }
}

// 🔥 Función principal para cargar catálogo de etapas en Paso 1
async function cargarCatalogoEtapas() {
  console.log('🔥 WIZARD: Cargando catálogo de etapas...');
  
  const catalogoContainer = document.getElementById('catalogoEtapas');
  if (!catalogoContainer) {
    console.error('❌ Contenedor de catálogo no encontrado');
    return;
  }
  
  try {
    // Mostrar loading
    catalogoContainer.innerHTML = `
      <div class="col-12 text-center py-4">
        <div class="spinner-border text-primary" role="status">
          <span class="visually-hidden">Cargando catálogo...</span>
        </div>
        <p class="text-muted mt-2">Cargando catálogo de etapas...</p>
      </div>
    `;
    
    // Obtener obra ID del modal o variable global
    let obraId = document.getElementById('wizardTareasModal')?.getAttribute('data-obra-id');
    if (!obraId) {
      obraId = window.obraId;
    }
    if (!obraId) {
      throw new Error('ID de obra no disponible');
    }
    
    console.log(`📡 WIZARD: Llamando API para obra ${obraId}`);
    
    // 🔥 Normalizar la respuesta del API
    const res = await fetch(`${PREF}/api/wizard-tareas/etapas?obra_id=${obraId}`, { 
      credentials: 'include' 
    });
    const json = await res.json();
    
    if (!res.ok) {
      throw new Error(json.error || `HTTP ${res.status}: ${res.statusText}`);
    }
    
    // 🔥 Usar las claves correctas
    const catalogo = Array.isArray(json) ? json : (json.etapas_catalogo || []);
    const creadas = new Set((json.etapas_creadas || []).map(e => e.slug || e.id));
    
    console.log('📦 WIZARD: Catálogo recibido:', { catalogo: catalogo.length, creadas: creadas.size });
    console.log('🔍 WIZARD: Etapas creadas:', Array.from(creadas));
    
    // 🔥 Render de cards - no marcar por defecto, solo checked disabled si ya está creada
    if (catalogo.length > 0) {
      const html = catalogo.map(e => {
        const ya = creadas.has(e.slug || e.id);
        console.log(`🔍 WIZARD: Etapa ${e.slug} - ya creada: ${ya}`);
        
        const cardClass = ya ? 'border-success bg-light-success' : 'border-light';
        const iconClass = ya ? 'text-success fas fa-check-circle' : 'text-primary fas fa-hammer';
        const badgeClass = ya ? 'badge bg-success' : 'badge bg-primary';
        const statusText = ya ? 'Ya agregada' : 'Disponible';
        
        return `
          <div class="col-md-6 col-lg-4 mb-3">
            <div class="card ${cardClass} h-100 etapa-catalog-card" 
                 data-etapa-nombre="${e.nombre}"
                 data-slug="${e.slug || ''}"
                 data-ya-creada="${ya}">
              <div class="card-body">
                <div class="d-flex align-items-start">
                  <div class="me-3">
                    <i class="${iconClass}" style="font-size: 1.5rem;"></i>
                  </div>
                  <div class="flex-grow-1">
                    <div class="form-check">
                      <input type="checkbox" class="form-check-input etapa-checkbox"
                             data-slug="${e.slug || ''}" ${ya ? 'checked disabled' : ''}>
                      <label class="form-check-label">
                        <h6 class="card-title mb-1">${e.nombre}</h6>
                      </label>
                    </div>
                    <div class="text-muted small">${e.descripcion || 'Etapa de construcción'}</div>
                    <div class="mt-2">
                      <span class="${badgeClass}">${statusText}</span>
                      ${e.duracion_estimada ? `<span class="badge bg-light text-dark ms-1">${e.duracion_estimada} días</span>` : ''}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        `;
      }).join('');
      
      catalogoContainer.innerHTML = html;
    } else {
      catalogoContainer.innerHTML = `
        <div class="col-12 text-center py-4">
          <p class="text-muted">No hay etapas disponibles en el catálogo.</p>
        </div>
      `;
    }
    
    // Rebind eventos de checkbox
    if (typeof rebindCatalogEvents === 'function') {
      rebindCatalogEvents();
    }
    
    // 🔥 Recalcular al terminar de pintar
    updateSelectionCounter();
    
    console.log('✅ WIZARD: Catálogo cargado correctamente');
    
  } catch (error) {
    console.error('❌ WIZARD: Error cargando catálogo:', error);
    catalogoContainer.innerHTML = `
      <div class="col-12 text-center py-4 text-danger">
        <i class="fas fa-exclamation-triangle fa-2x mb-2"></i>
        <p class="mb-2">Error cargando catálogo de etapas</p>
        <p class="small">${error.message}</p>
        <button class="btn btn-outline-primary btn-sm mt-2" onclick="window.cargarCatalogoEtapas()">
          <i class="fas fa-refresh me-1"></i>Reintentar
        </button>
      </div>
    `;
  }
}

// 🔥 Re-bind eventos del catálogo después de cargar
function rebindCatalogEvents() {
  // Checkbox selection
  document.querySelectorAll('.etapa-checkbox').forEach(checkbox => {
    checkbox.addEventListener('change', updateSelectionCounter);
  });
  
  // Card click to toggle checkbox  
  document.querySelectorAll('.etapa-catalog-card').forEach(card => {
    if (!card.dataset.yaCreada || card.dataset.yaCreada === 'false') {
      card.style.cursor = 'pointer';
      card.addEventListener('click', (e) => {
        if (e.target.type !== 'checkbox') {
          const checkbox = card.querySelector('.etapa-checkbox');
          if (checkbox && !checkbox.disabled) {
            checkbox.checked = !checkbox.checked;
            updateSelectionCounter();
          }
        }
      });
    }
  });
  
  console.log('✅ WIZARD: Eventos del catálogo vinculados');
}

// 🔥 Habilitar "Siguiente" cuando haya selección (no deshabilitada)
function updateSelectionCounter() {
  const count = document.querySelectorAll('.etapa-checkbox:checked:not(:disabled)').length;
  console.log(`📊 WIZARD: Contador actualizado - ${count} etapas seleccionadas`);
  
  // Actualizar contador
  const counter = document.getElementById('contadorSeleccionadas');
  if (counter) {
    counter.textContent = count;
  }
  
  // Habilitar/deshabilitar botón "Siguiente"
  const btnSig = document.getElementById('wizardBtnSiguiente');
  if (btnSig) {
    btnSig.disabled = (count === 0);
    btnSig.classList.toggle('btn-primary', count > 0);
    btnSig.classList.toggle('btn-secondary', count === 0);
  }
}

// 🔥 Agregar funciones globales para botones existentes
window.seleccionarTodasLasEtapas = function() {
  document.querySelectorAll('.etapa-checkbox:not(:disabled)').forEach(cb => cb.checked = true);
  updateSelectionCounter();
  console.log('✅ WIZARD: Todas las etapas seleccionadas');
};

window.deseleccionarTodasLasEtapas = function() {
  document.querySelectorAll('.etapa-checkbox:not(:disabled)').forEach(cb => cb.checked = false);
  updateSelectionCounter();
  console.log('✅ WIZARD: Todas las etapas deseleccionadas');
};

// 🔥 Actualizar contador cuando cambie cualquier checkbox
document.addEventListener('change', (e) => {
  if (e.target.matches('.etapa-checkbox')) {
    updateSelectionCounter();
  }
});

// 🔥 Enganche "Siguiente" con applyCatalogAndAdvance si es necesario
document.addEventListener('DOMContentLoaded', () => {
  const siguienteBtn = document.getElementById('wizardBtnSiguiente');
  if (siguienteBtn) {
    siguienteBtn.addEventListener('click', (ev) => {
      const count = document.querySelectorAll('.etapa-checkbox:checked:not(:disabled)').length;
      console.log(`🔥 WIZARD: Botón Siguiente clickeado - ${count} etapas seleccionadas`);
      
      // Si estamos en paso 1 y hay selecciones, aplicar catálogo
      if (window.wizardPasoActual === 1 && count > 0 && typeof window.applyCatalogAndAdvance === 'function') {
        console.log('🔥 WIZARD: Aplicando catálogo y avanzando...');
        ev.preventDefault();
        window.applyCatalogAndAdvance(); // agrega y luego avanza al Paso 2
      }
    });
  }
});

// 🔥 EXPONER FUNCIONES AL GLOBAL
window.cargarCatalogoEtapas = cargarCatalogoEtapas;
window.rebindCatalogEvents = rebindCatalogEvents;
window.updateSelectionCounter = updateSelectionCounter;

// 🔥 Inicialización automática cuando el DOM está listo
document.addEventListener('DOMContentLoaded', () => {
  console.log('🧙‍♂️ WIZARD: Sistema inicializado');
  
  // Verificar que las funciones estén disponibles
  console.log('📋 WIZARD: Funciones disponibles:', {
    cargarCatalogoEtapas: typeof window.cargarCatalogoEtapas,
    rebindCatalogEvents: typeof window.rebindCatalogEvents,  
    updateSelectionCounter: typeof window.updateSelectionCounter
  });
});

// 🔥 Event listener DELEGADO para modal wizard
document.addEventListener('shown.bs.modal', (e) => {
  if (e.target && e.target.id === 'wizardTareasModal') {
    console.debug('🔥 [WIZARD] Modal shown - iniciando carga de catálogo');
    
    // Habilitar botón siguiente
    document.getElementById('wizardBtnSiguiente')?.removeAttribute('disabled');
    
    // Ocultar mensajes legacy
    document.querySelectorAll('.wizard-legacy-note').forEach(el => el.remove());
    
    // 🔥 CARGAR CATÁLOGO DE ETAPAS
    if (typeof window.cargarCatalogoEtapas === 'function') {
      window.cargarCatalogoEtapas();
    } else {
      console.error('❌ [WIZARD] Función cargarCatalogoEtapas no disponible');
    }
  }
});

// 🔥 Backup: trigger también en click del botón wizard
document.addEventListener('click', (ev) => {
  const btn = ev.target.closest('[data-bs-target="#wizardTareasModal"]');
  if (btn) {
    console.debug('🔥 [WIZARD] Botón wizard clickeado');
    setTimeout(() => {
      if (typeof window.cargarCatalogoEtapas === 'function') {
        window.cargarCatalogoEtapas();
      }
    }, 100); // Small delay para que el modal se abra
  }
});

console.log('✅ WIZARD: Archivo wizard.js completamente cargado');