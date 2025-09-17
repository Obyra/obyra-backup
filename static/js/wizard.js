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

// 🔥 Lógica de navegación del wizard - Remover el event listener anterior (será reemplazado abajo)

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

// 🔥 LÓGICA DE NAVEGACIÓN DEL WIZARD (después de Bootstrap)
(function () {
  const m = document.getElementById('wizardTareasModal');
  const getSel = () => [...m.querySelectorAll('.etapa-checkbox:checked:not(:disabled)')]
                        .map(cb => cb.dataset.slug).filter(Boolean);
  window.getEtapasSeleccionadas = getSel;

  window.gotoPaso = function (n) {
    console.log(`🔥 WIZARD: Navegando a paso ${n}`);
    
    // Buscar por data-paso
    const panes = [...m.querySelectorAll('[data-paso]'), ...m.querySelectorAll('[id^="wizardPaso"]')];
    if (panes.length) {
      panes.forEach(el => {
        const num = Number(el.getAttribute('data-paso') || (el.id.match(/wizardPaso(\d+)/)||[])[1]);
        el.classList.toggle('d-none', num !== n);
      });
      return;
    }
    
    // Buscar por tabs Bootstrap
    const tabBtn = m.querySelector(`[data-bs-toggle="tab"][data-bs-target="#wizardPaso${n}"]`);
    if (tabBtn) { 
      const Tab = window.bootstrap?.Tab; 
      Tab ? new Tab(tabBtn).show() : tabBtn.click(); 
      return; 
    }
    
    // Buscar por IDs wizardStep1, wizardStep2, etc.
    const stepById = m.querySelector(`#wizardStep${n}`);
    if (stepById) {
      // Ocultar todos los pasos y mostrar el seleccionado
      [...m.querySelectorAll('[id^="wizardStep"]')].forEach(el => el.classList.add('d-none'));
      stepById.classList.remove('d-none');
      return;
    }
    
    // Fallback genérico
    const generic = [...m.querySelectorAll('.wizard-content')];
    if (generic.length) {
      generic.forEach((el,i)=> el.classList.toggle('d-none', i !== (n-1)));
    }
  };

  window.applyCatalogAndAdvance = function () {
    const slugs = getSel();
    console.log(`🔥 WIZARD: Aplicando catálogo - ${slugs.length} etapas seleccionadas:`, slugs);
    if (!slugs.length) return;
    
    // Aplicar selección (mismo que el botón verde)
    document.getElementById('btnAgregarEtapasSel')?.click(); 
    
    // Navegar a paso 2 y cargar tareas
    window.gotoPaso(2);
    
    // Obtener obra_id del modal
    const obraId = m.dataset.obraId || document.querySelector('[data-obra-id]')?.dataset.obraId;
    if (obraId && typeof window.loadTareasWizard === 'function') {
      window.loadTareasWizard(obraId, slugs);
    }
  };

  function connectWizardNav() {
    const btnSig = document.getElementById('wizardBtnSiguiente');
    if (btnSig && !btnSig.dataset.bound) {
      btnSig.dataset.bound = '1';
      btnSig.type = 'button';
      btnSig.addEventListener('click', (ev) => {
        console.log(`🔥 WIZARD: Botón Siguiente clickeado`);
        if (getSel().length > 0) { 
          ev.preventDefault(); 
          window.applyCatalogAndAdvance(); 
        }
      });
      console.log('✅ WIZARD: Navegación conectada');
    }
  }

  document.addEventListener('shown.bs.modal', (ev) => {
    if (ev.target?.id === 'wizardTareasModal') {
      console.log('🔥 WIZARD: Modal mostrado, conectando navegación');
      connectWizardNav();
    }
  });
})();

// 🔥 CARGAR TAREAS PARA EL PASO 2
window.loadTareasWizard = async function(obraId, slugs) {
  console.log(`🔥 WIZARD: Cargando tareas para obra ${obraId}, etapas:`, slugs);
  
  const m = document.getElementById('wizardTareasModal');
  const list = m.querySelector('#wizardListaTareas') || m.querySelector('#wizardStep2');
  const spin = m.querySelector('#wizardSpinnerTareas');
  
  // Mostrar spinner y limpiar contenido
  if (spin) spin.classList.remove('d-none');
  if (list) list.innerHTML = '';
  
  try {
    // Llamar al API de tareas (ajustar según su implementación)
    const res = await fetch('/obras/api/wizard-tareas/tareas', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      credentials: 'include',
      body: JSON.stringify({ obra_id: parseInt(obraId), etapas: slugs })
    });
    
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    
    const json = await res.json();
    const tareas = json.tareas_catalogo || json.tareas || json.data || [];
    
    // Ocultar spinner
    if (spin) spin.classList.add('d-none');
    
    // Renderizar tareas
    if (list) {
      list.innerHTML = tareas.length
        ? `<div class="mb-3">
             <h6 class="text-primary">Tareas disponibles (${tareas.length}):</h6>
             <div class="row">${
               tareas.map(t => `
                 <div class="col-md-6 mb-2">
                   <div class="form-check">
                     <input class="form-check-input tarea-checkbox" type="checkbox" 
                            data-id="${t.id}" data-slug="${t.slug || t.nombre}" 
                            id="tarea-${t.id}">
                     <label class="form-check-label" for="tarea-${t.id}">
                       <strong>${t.nombre}</strong>
                       ${t.descripcion ? `<br><small class="text-muted">${t.descripcion}</small>` : ''}
                     </label>
                   </div>
                 </div>
               `).join('')
             }</div>
           </div>`
        : '<div class="text-muted text-center p-4">No hay tareas disponibles para las etapas seleccionadas.</div>';
    }
    
    console.log(`✅ WIZARD: ${tareas.length} tareas cargadas exitosamente`);
    
  } catch (error) {
    console.error('❌ WIZARD: Error cargando tareas:', error);
    
    // Ocultar spinner y mostrar error
    if (spin) spin.classList.add('d-none');
    if (list) {
      list.innerHTML = `<div class="alert alert-warning">
        <h6>No se pudieron cargar las tareas</h6>
        <p class="mb-0">Error: ${error.message}</p>
        <button class="btn btn-sm btn-outline-primary mt-2" onclick="window.loadTareasWizard(${obraId}, ${JSON.stringify(slugs)})">
          Reintentar
        </button>
      </div>`;
    }
  }
};