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
    
    // Llamar API del wizard
    const obraId = window.obraId;
    if (!obraId) {
      throw new Error('ID de obra no disponible');
    }
    
    console.log(`📡 WIZARD: Llamando API para obra ${obraId}`);
    const response = await fetchJSON(`${PREF}/api/wizard-tareas/etapas?obra_id=${obraId}`);
    
    if (!response.ok) {
      throw new Error(response.error || 'Error cargando catálogo');
    }
    
    const { etapas_catalogo, etapas_creadas } = response;
    console.log('📦 WIZARD: Catálogo recibido:', { etapas_catalogo: etapas_catalogo?.length, etapas_creadas: etapas_creadas?.length });
    
    // Construir HTML del catálogo
    let catalogoHTML = '';
    if (etapas_catalogo && etapas_catalogo.length > 0) {
      etapas_catalogo.forEach(etapa => {
        const yaCreada = etapas_creadas.some(creada => creada.slug === etapa.slug);
        const cardClass = yaCreada ? 'border-success bg-light-success' : 'border-light';
        const iconClass = yaCreada ? 'text-success fas fa-check-circle' : 'text-primary fas fa-hammer';
        const badgeClass = yaCreada ? 'badge bg-success' : 'badge bg-primary';
        const statusText = yaCreada ? 'Ya agregada' : 'Disponible';
        
        catalogoHTML += `
          <div class="col-md-6 col-lg-4 mb-3">
            <div class="card ${cardClass} h-100 etapa-catalog-card" 
                 data-slug="${etapa.slug}" 
                 data-nombre="${etapa.nombre}"
                 data-ya-creada="${yaCreada}">
              <div class="card-body">
                <div class="d-flex align-items-start">
                  <div class="me-3">
                    <i class="${iconClass}" style="font-size: 1.5rem;"></i>
                  </div>
                  <div class="flex-grow-1">
                    <h6 class="card-title mb-2">${etapa.nombre}</h6>
                    <p class="card-text text-muted small">${etapa.descripcion || 'Etapa de construcción'}</p>
                    <div class="mt-2">
                      <span class="${badgeClass}">${statusText}</span>
                      ${etapa.duracion_estimada ? `<span class="badge bg-light text-dark ms-1">${etapa.duracion_estimada} días</span>` : ''}
                    </div>
                  </div>
                  <div class="ms-2">
                    <input type="checkbox" 
                           class="form-check-input etapa-checkbox" 
                           data-slug="${etapa.slug}"
                           ${yaCreada ? 'checked disabled' : ''}>
                  </div>
                </div>
              </div>
            </div>
          </div>
        `;
      });
    } else {
      catalogoHTML = `
        <div class="col-12 text-center py-4">
          <p class="text-muted">No hay etapas disponibles en el catálogo.</p>
        </div>
      `;
    }
    
    // Actualizar contenido
    catalogoContainer.innerHTML = catalogoHTML;
    
    // Rebind eventos de checkbox
    rebindCatalogEvents();
    
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

// 🔥 Actualizar contador de selección
function updateSelectionCounter() {
  const checkedBoxes = document.querySelectorAll('.etapa-checkbox:checked:not(:disabled)');
  const counter = document.getElementById('contadorSeleccionadas');
  if (counter) {
    counter.textContent = checkedBoxes.length;
  }
  
  // Enable/disable agregar button
  const addBtn = document.querySelector('[onclick*="applyCatalogAndAdvance"]');
  if (addBtn) {
    addBtn.disabled = checkedBoxes.length === 0;
    addBtn.classList.toggle('btn-success', checkedBoxes.length > 0);
    addBtn.classList.toggle('btn-secondary', checkedBoxes.length === 0);
  }
}

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