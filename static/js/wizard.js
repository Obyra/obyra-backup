// 🧙‍♂️ WIZARD TAREAS - Sistema de creación masiva de tareas por etapas
// Versión ESTABILIZADA con event delegation y polyfills robustos

console.log('🧙‍♂️ WIZARD: Iniciando sistema estabilizado...');

// =================== NAVEGACIÓN UNIFICADA CON VALIDACIONES ===================
(function ensureUnifiedNavigation(){
  // 🎯 STEP VALIDATORS: Validaciones centralizadas por paso
  const STEP_VALIDATORS = {
    1: () => {
      const etapasSeleccionadas = document.querySelectorAll('.etapa-checkbox:checked:not(:disabled)').length;
      if (etapasSeleccionadas === 0) {
        throw new Error('Debe seleccionar al menos una etapa');
      }
      console.log(`✅ STEP 1: ${etapasSeleccionadas} etapas seleccionadas`);
      return true;
    },
    
    2: () => {
      const tareasSeleccionadas = document.querySelectorAll('.tarea-checkbox:checked:not(:disabled)').length;
      if (tareasSeleccionadas === 0) {
        throw new Error('Debe seleccionar al menos una tarea');
      }
      console.log(`✅ STEP 2: ${tareasSeleccionadas} tareas seleccionadas`);
      return true;
    },
    
    3: () => {
      const rows = document.querySelectorAll('#tablaDatosWizard tbody tr');
      const hasEmptyRequired = Array.from(rows).some(row => {
        const fechaInicio = row.querySelector('.fecha-inicio')?.value;
        const fechaFin = row.querySelector('.fecha-fin')?.value;
        const cantidad = row.querySelector('.cantidad')?.value;
        return !fechaInicio || !fechaFin || !cantidad;
      });
      if (hasEmptyRequired) {
        throw new Error('Complete todos los campos requeridos en la tabla');
      }
      console.log(`✅ STEP 3: ${rows.length} tareas validadas`);
      return true;
    }
  };

  // 🎯 UNIFIED NAVIGATION: Una sola función con validaciones
  window.gotoPaso = function(step, options = {}){
    const { skipValidation = false, force = false } = options;
    
    // 🛡️ Validation: Check current step before navigation
    if (!skipValidation && !force) {
      const currentStep = window.WZ_STATE?.currentStep || 1;
      const validator = STEP_VALIDATORS[currentStep];
      
      if (validator) {
        try {
          validator();
        } catch (error) {
          console.warn(`❌ NAVIGATION: Step ${currentStep} validation failed:`, error.message);
          alert(error.message);
          return false;
        }
      }
    }
    
    // 🔍 Find target pane with robust selectors
    const pane = document.querySelector(
      `[data-wz-step="${step}"], #wizardStep${step}, #wizard-paso${step}, #paso${step}, #wizardPaso${step}, #wizard-step${step}, #step${step}`
    );
    
    if (!pane) { 
      console.error(`❌ gotoPaso: pane no encontrado para paso ${step}. Selectores probados: [data-wz-step="${step}"], #wizardStep${step}, etc.`);
      return false; 
    }
    
    console.log(`✅ gotoPaso: Navigating to step ${step}`, { id: pane.id, classes: pane.className });

    // 🎯 Update global state FIRST
    window.WZ_STATE = window.WZ_STATE || {};
    window.WZ_STATE.currentStep = step;
    
    // 🎨 Update UI: Hide all, show target
    const cont = pane.closest('.tab-content') || document;
    cont.querySelectorAll('.tab-pane').forEach(el => {
      el.classList.remove('active','show');
      el.setAttribute('aria-hidden','true');
    });
    pane.classList.add('active','show');
    pane.removeAttribute('aria-hidden');
    
    // 🎯 Update navigation tabs
    const tab = document.querySelector(`[data-bs-target="#${pane.id}"], a[href="#${pane.id}"]`);
    if (tab) {
      const nav = tab.closest('.nav') || document;
      nav.querySelectorAll('.nav-link.active').forEach(l=>l.classList.remove('active'));
      tab.classList.add('active');
    }
    
    console.log(`🎯 gotoPaso: Step ${step} activated successfully`);
    return true;
  };
  
  // 🔄 NAVIGATION HELPERS: Convenient methods
  window.nextStep = function() {
    const currentStep = window.WZ_STATE?.currentStep || 1;
    return window.gotoPaso(currentStep + 1);
  };
  
  window.prevStep = function() {
    const currentStep = window.WZ_STATE?.currentStep || 1;
    if (currentStep > 1) {
      return window.gotoPaso(currentStep - 1, { skipValidation: true });
    }
    return false;
  };
  
  window.forceStep = function(step) {
    return window.gotoPaso(step, { force: true, skipValidation: true });
  };
  
  console.log('🎯 UNIFIED NAVIGATION: Loaded with centralized validations');
})();

// =================== UTILIDADES ===================
// helper de rutas absolutas
const api = (p) => p.startsWith('/') ? p : `/${p}`;

// fetch JSON que grite si viene HTML
async function fetchJSON(url, opts = {}) {
  const r = await fetch(url, { credentials: 'same-origin', ...opts });
  const ctype = r.headers.get('content-type') || '';
  const text = await r.text();
  if (!r.ok) {
    throw new Error(ctype.includes('application/json')
      ? (JSON.parse(text).error || `HTTP ${r.status}`)
      : `HTTP ${r.status} (no JSON): ${text.slice(0,120)}`);
  }
  if (!ctype.includes('application/json')) {
    throw new Error(`Respuesta no-JSON del servidor: ${text.slice(0,120)}`);
  }
  return JSON.parse(text);
}

// =================== EVENT DELEGATION INTERCEPTORS ===================

// 🚫 DISABLED: FINALIZAR Paso 3 -> 4 (Now handled in detalle.html)
// Eliminado para evitar listeners duplicados que causan doble POST

// 🚫 DISABLED: CONFIRMAR Paso 4 -> Cerrar (Now handled in detalle.html)
// Eliminado para evitar listeners duplicados que interfieren con updateStepDisplay()

// Guard anti-rebote a Paso 2 durante el lock
if (!window.__WZ_GUARD_INSTALLED__) {
  window.__WZ_GUARD_INSTALLED__ = true;
  document.addEventListener('click', (ev) => {
    const a = ev.target.closest('a[href="#paso2"],a[href="#wizardPaso2"]');
    if (!a) return;
    if ((window.__WZ_NAV_LOCK_UNTIL__||0) > Date.now()) {
      ev.preventDefault(); ev.stopPropagation(); ev.stopImmediatePropagation?.();
      console.log('🚫 WIZARD: Click a Paso 2 bloqueado (lock activo)');
    }
  }, { capture: true });
  
  window.addEventListener('hashchange', (e) => {
    if ((window.__WZ_NAV_LOCK_UNTIL__||0) > Date.now() && /paso2/i.test(location.hash)) {
      history.replaceState(null,'','#'); 
      e.stopImmediatePropagation?.();
      console.log('🚫 WIZARD: Hashchange a Paso 2 bloqueado');
    }
  }, { capture: true });
}

// =================== CATÁLOGO DE ETAPAS ===================
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
    
    // 🔥 Usar ruta absoluta
    const json = await fetchJSON(api(`obras/api/wizard-tareas/etapas?obra_id=${obraId}`));
    
    // 🔥 Usar las claves correctas
    const catalogo = Array.isArray(json) ? json : (json.etapas_catalogo || []);
    const creadas = new Set((json.etapas_creadas || []).map(e => e.slug || e.id));
    
    console.log('📦 WIZARD: Catálogo recibido:', { catalogo: catalogo.length, creadas: creadas.size });
    
    // 🔥 Render de cards - no marcar por defecto, solo checked disabled si ya está creada
    if (catalogo.length > 0) {
      catalogoContainer.innerHTML = catalogo.map(etapa => {
        const yaCreada = creadas.has(etapa.slug);
        const badgeClass = yaCreada ? 'bg-success' : 'bg-primary';
        const badgeText = yaCreada ? 'Ya agregada' : 'Disponible';
        const cardClass = yaCreada ? 'border-success' : 'border-light';
        const disabledAttr = yaCreada ? 'disabled' : '';
        const checkedAttr = yaCreada ? 'checked' : '';
        
        return `
          <div class="col-md-6 col-lg-4 mb-3">
            <div class="card h-100 etapa-catalog-card ${cardClass}" data-ya-creada="${yaCreada}">
              <div class="card-body">
                <div class="d-flex align-items-start justify-content-between">
                  <div class="form-check">
                    <input class="form-check-input etapa-checkbox" type="checkbox" 
                           name="etapa" value="${etapa.id}" data-etapa-id="${etapa.id}"
                           data-slug="${etapa.slug}" data-nombre="${etapa.nombre}"
                           id="etapa-${etapa.slug}" ${disabledAttr} ${checkedAttr}>
                    <label class="form-check-label fw-bold" for="etapa-${etapa.slug}">
                      ${etapa.nombre}
                    </label>
                  </div>
                  <span class="badge ${badgeClass} ms-2">${badgeText}</span>
                </div>
                ${etapa.descripcion ? `<p class="text-muted small mt-2 mb-0">${etapa.descripcion}</p>` : ''}
              </div>
            </div>
          </div>
        `;
      }).join('');
    } else {
      catalogoContainer.innerHTML = `
        <div class="col-12 text-center py-4">
          <i class="fas fa-info-circle fa-2x text-muted mb-2"></i>
          <p class="text-muted">No hay etapas disponibles en el catálogo</p>
        </div>
      `;
    }
    
    // Rebind eventos de checkbox
    if (typeof rebindCatalogEvents === 'function') {
      rebindCatalogEvents();
    }
    
    // 🎯 REHIDRATAR: Restaurar checkboxes desde estado global tras render
    rehydrateChecksFromState();
    
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

function rebindCatalogEvents() {
  // 🎯 STEP 2: Set-based checkbox handling - NO refrescar contenedor
  const container = document.getElementById('catalogoEtapas');
  if (container) {
    // Remove old listeners to avoid duplicates
    container.removeEventListener('change', handleEtapaCheckboxChange);
    container.removeEventListener('click', handleCardClick);
    
    // Add delegated event listeners
    container.addEventListener('change', handleEtapaCheckboxChange);
    container.addEventListener('click', handleCardClick);
  }
  
  console.log('✅ WIZARD: Eventos de catálogo rebindeados con Set-based logic');
}

// 🎯 STEP 2: Handler para checkboxes usando Set (NO DOM)
function handleEtapaCheckboxChange(e) {
  const cb = e.target.closest('input[type="checkbox"][data-etapa-id]');
  if (!cb) return;
  
  const id = String(cb.dataset.etapaId);
  if (cb.checked) {
    window.WZ_STATE.etapasSel.add(id);
  } else {
    window.WZ_STATE.etapasSel.delete(id);
  }
  updateEtapasBadge();
  // ❌ NO refrescar contenedor acá - mantener estado
  console.log(`🎯 STATE: Etapa ${id} ${cb.checked ? 'agregada' : 'removida'}. Total: ${window.WZ_STATE.etapasSel.size}`);
}

// 🎯 Handler para click en cards
function handleCardClick(e) {
  const card = e.target.closest('.etapa-catalog-card');
  if (!card) return;
  if (card.dataset.yaCreada === 'true') return; // Skip disabled cards
  
  if (e.target.type !== 'checkbox') {
    const checkbox = card.querySelector('.etapa-checkbox');
    if (checkbox && !checkbox.disabled) {
      checkbox.checked = !checkbox.checked;
      // Trigger change event to update Set
      checkbox.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }
}

// 🔥 LEGACY: Mantener compatibilidad (deprecated - usar updateEtapasBadge)
function updateSelectionCounter() {
  console.log(`⚠️ DEPRECATED: updateSelectionCounter() - usar updateEtapasBadge() en su lugar`);
  updateEtapasBadge();
}

// 🔥 FUNCIÓN CRÍTICA: Actualizar panel "Tareas Seleccionadas" en tiempo real
function updateTaskSelectionPanel() {
  const checkedTasks = document.querySelectorAll('.tarea-checkbox:checked:not(:disabled)');
  const count = checkedTasks.length;
  console.log(`📊 WIZARD: Panel tareas actualizado - ${count} tareas seleccionadas`);
  
  // Buscar panel "Tareas Seleccionadas" por varios posibles IDs/selectores
  const panel = document.getElementById('tareas-seleccionadas-list') ||
               document.getElementById('tareasSeleccionadasPanel') || 
               document.querySelector('.tareas-seleccionadas') ||
               document.querySelector('[data-panel="tareas-seleccionadas"]') ||
               document.querySelector('.panel-selected-tasks');
  
  if (panel) {
    if (count === 0) {
      panel.innerHTML = '<div class="text-muted">Ninguna tarea seleccionada</div>';
    } else {
      const tasksList = Array.from(checkedTasks).map(checkbox => {
        const name = checkbox.getAttribute('data-nombre') || 'Tarea sin nombre';
        return `<div class="small mb-1">✓ ${name}</div>`;
      }).join('');
      panel.innerHTML = `<div class="mb-2"><strong>Tareas seleccionadas (${count}):</strong></div>${tasksList}`;
    }
  } else {
    console.warn('⚠️ WIZARD: Panel "Tareas Seleccionadas" no encontrado en DOM');
  }
}

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

// 🎯 DISABLED: Replaced by Set-based delegation in rebindCatalogEvents()
// Old global delegation removed to prevent conflicts with Set-based approach

// 🔥 EXPONER FUNCIONES AL GLOBAL
window.cargarCatalogoEtapas = cargarCatalogoEtapas;
window.rebindCatalogEvents = rebindCatalogEvents;
window.updateSelectionCounter = updateSelectionCounter;

// =================== ESTADO GLOBAL DEL WIZARD ===================
window.WZ_STATE = window.WZ_STATE || { 
  tareasSel: [],
  // 🛡️ GUARDS ANTI-DUPLICADO
  mutexes: new Set(),           // Track active operations
  requestCache: new Map(),      // Cache identical requests
  buttonStates: new Map(),      // Track button disabled states
  // 🎯 FUENTE ÚNICA DE VERDAD: Set global para etapas seleccionadas
  etapasSel: new Set()
};

// 🎯 STEP 1: Helper functions for Set-based selection
function getSelectedEtapaIds() { 
  return [...window.WZ_STATE.etapasSel]; 
}

function updateEtapasBadge() {
  const n = window.WZ_STATE.etapasSel.size;
  const btn = document.getElementById('btnAgregarEtapas');
  if (btn) {
    const countSpan = btn.querySelector('.count') || btn.querySelector('.badge');
    if (countSpan) {
      countSpan.textContent = n;
    }
    btn.disabled = n === 0;
    console.log(`🎯 STATE: Badge actualizado - ${n} etapas seleccionadas`);
  }
}

// 🎯 STEP 3: Rehidratar checkboxes desde el estado
function rehydrateChecksFromState() {
  document
    .querySelectorAll('#catalogoEtapas input[type="checkbox"][data-etapa-id]')
    .forEach(cb => {
      const id = String(cb.dataset.etapaId);
      cb.checked = window.WZ_STATE.etapasSel.has(id);
    });
  updateEtapasBadge();
  console.log(`🎯 STATE: Rehidratados ${window.WZ_STATE.etapasSel.size} checkboxes desde estado global`);
}

// Opciones/equipos
window.ensureOpciones = async function (obraId) {
  if (window.WZ_STATE.opciones) return window.WZ_STATE.opciones;

  try {
    const data = await fetchJSON(api(`obras/api/wizard-tareas/opciones?obra_id=${obraId}`));
    window.WZ_STATE.opciones = data;
    return data;
    
  } catch (error) {
    console.error('❌ WIZARD: Error cargando opciones:', error);
    return { unidades: ['h'], usuarios: [], equipo: [] };
  }
};

// collectPaso3Payload - Recopilar datos del Paso 3
window.collectPaso3Payload = function() {
  const modal = document.getElementById('wizardTareasModal');
  const rows = [...modal.querySelectorAll('#wizardStep3 #tablaDatosWizard tbody tr, #paso3 #tablaDatosWizard tbody tr')];
  const obraId = Number(modal?.getAttribute('data-obra-id') || window.OBRA_ID || 0);
  
  const tareas = rows.map((row, i) => {
    const getData = (name) => row.querySelector(`[name="rows[${i}][${name}]"]`)?.value || '';
    const tareaData = window.WZ_STATE.tareasSel?.[i] || {};
    
    return {
      etapa_slug: tareaData.etapa_slug || '',  // Usar slug de la plantilla
      nombre: row.children[1]?.textContent?.trim() || '',
      fecha_inicio: getData('inicio'),
      fecha_fin: getData('fin'),
      horas: Number(getData('horas')) || 8,
      cantidad: Number(getData('cantidad')) || 1,
      unidad: getData('unidad'),
      asignado_usuario_id: getData('asignado') || null,
      prioridad: getData('prioridad') || 'media'
    };
  });
  
  return {
    obra_id: obraId,
    tareas: tareas.filter(t => t.etapa_slug)  // Filtrar tareas con etapa_slug válido
  };
};

// populatePaso3 - BLOQUE CANÓNICO
window.populatePaso3 = async function() {
  const modal = document.getElementById('wizardTareasModal');
  const tbody = modal.querySelector('#tablaDatosWizard tbody');
  const obraId = modal.dataset.obraId || window.obraId;
  
  if (!tbody || !window.WZ_STATE.tareasSel?.length) {
    console.warn('⚠️ WIZARD: No hay tareas seleccionadas o tabla no encontrada');
    return;
  }

  // Cargar opciones (unidades y equipo) - Ruta absoluta
  const opciones = await window.ensureOpciones(obraId);
  const unidades = opciones.unidades || ['h', 'días', 'und'];
  const equipo = opciones.usuarios || opciones.equipo || [];  // Fix: Backend returns 'usuarios', not 'equipo'

  // Generar filas
  const filas = window.WZ_STATE.tareasSel.map((tarea, i) => {
    const unidadesOpts = unidades.map(u => `<option value="${u}">${u}</option>`).join('');
    
    // Modificación: Agregar placeholder y no pre-seleccionar usuario
    const equipoOpts = [
      '<option value="">— Seleccioná —</option>',  // Placeholder
      ...equipo.map(user => `<option value="${user.id}">${user.nombre}</option>`)
    ].join('');

    return `
      <tr data-index="${i}">
        <td class="small text-muted">${tarea.etapa_slug || 'Sin etapa'}</td>
        <td class="fw-bold">${tarea.nombre}</td>
        <td><input type="date" name="rows[${i}][inicio]" class="form-control form-control-sm"></td>
        <td><input type="date" name="rows[${i}][fin]" class="form-control form-control-sm"></td>
        <td><input type="number" name="rows[${i}][horas]" value="8" min="1" class="form-control form-control-sm" style="width:70px"></td>
        <td><input type="number" name="rows[${i}][cantidad]" value="1" min="1" class="form-control form-control-sm" style="width:70px"></td>
        <td>
          <select name="rows[${i}][unidad]" class="form-select form-select-sm" style="width:80px">
            ${unidadesOpts}
          </select>
        </td>
        <td>
          <select name="rows[${i}][asignado]" class="form-select form-select-sm" style="min-width:120px">
            ${equipoOpts}
          </select>
        </td>
        <td>
          <select name="rows[${i}][prioridad]" class="form-select form-select-sm" style="width:90px">
            <option value="baja">Baja</option>
            <option value="media" selected>Media</option>
            <option value="alta">Alta</option>
          </select>
        </td>
      </tr>
    `;
  }).join('');

  tbody.innerHTML = filas;
  console.log(`✅ WIZARD: ${window.WZ_STATE.tareasSel.length} filas generadas en Paso 3`);
};

// =================== CARGA DE TAREAS PASO 2 (CATÁLOGO) ===================
window.loadTareasWizard = async function(obraId, slugs) {
  console.log(`🔥 WIZARD: Cargando tareas del CATÁLOGO para obra ${obraId}, etapas:`, slugs);
  
  const m = document.getElementById('wizardTareasModal');
  const list = m.querySelector('#wizardListaTareas') || m.querySelector('#wizardStep2');
  const spin = m.querySelector('#wizardSpinnerTareas');
  
  console.log(`🔍 WIZARD: Contenedores encontrados - Modal: ${!!m}, ListaTareas: ${!!list}, Spinner: ${!!spin}`);
  console.log(`🔍 WIZARD: Selector usado: #wizardListaTareas`);
  
  if (spin) spin.classList.remove('d-none');
  if (list) {
    list.innerHTML = '';
    console.log(`🔍 WIZARD: Lista limpiada. Contenedor actual:`, list);
  }
  
  try {
    // USAR EL ENDPOINT DEL CATÁLOGO (NO DB REAL) - Ruta absoluta
    const json = await fetchJSON(api(`obras/api/wizard-tareas/tareas?obra_id=${obraId}&etapas=${encodeURIComponent(JSON.stringify(slugs))}`), {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ obra_id: parseInt(obraId), etapas: slugs })
    });
    
    const tareas = json.tareas_catalogo || json.tareas || json.data || [];
    
    console.log(`🔍 WIZARD: Datos recibidos del backend:`, { 
      json, 
      tareasExtracted: tareas,
      primerasTareas: tareas.slice(0, 3)
    });
    
    if (spin) spin.classList.add('d-none');
    
    if (list) {
      const html = tareas.length
        ? `<div class="mb-3">
             <h6 class="text-primary">📋 Plantillas disponibles (${tareas.length}):</h6>
             <div class="row">${
               tareas.map((t, index) => {
                 console.log(`🔍 WIZARD: Generando checkbox ${index}:`, { 
                   tarea: t, 
                   id: t.id, 
                   nombre: t.nombre, 
                   etapaSlug: t.etapa_slug 
                 });
                 
                 return `
                   <div class="col-md-6 mb-2">
                     <div class="form-check">
                       <input class="form-check-input tarea-checkbox" type="checkbox" 
                              name="tasks[]"
                              data-id="${t.id || ''}" 
                              data-nombre="${t.nombre || ''}"
                              data-etapa="${t.etapa_slug || ''}"
                              data-descripcion="${t.descripcion || ''}"
                              data-horas="${t.horas || '8'}"
                              value="${t.id || ''}"
                              id="tarea-${t.id || index}">
                       <label class="form-check-label" for="tarea-${t.id || index}">
                         <strong>${t.nombre || 'Tarea sin nombre'}</strong>
                         ${t.descripcion ? `<br><small class="text-muted">${t.descripcion}</small>` : ''}
                         <small class="text-info d-block">⏱️ ${t.horas || 0}h estimadas</small>
                       </label>
                     </div>
                   </div>
                 `;
               }).join('')
             }</div>
           </div>`
        : '<div class="text-muted text-center p-4">📝 No hay plantillas disponibles para las etapas seleccionadas.</div>';
      
      list.innerHTML = html;
      
      // 🔥 REBINDEAR EVENT LISTENERS para tareas (CRÍTICO para panel "Tareas Seleccionadas")
      setTimeout(() => {
        document.querySelectorAll('.tarea-checkbox').forEach(checkbox => {
          checkbox.addEventListener('change', updateTaskSelectionPanel);
        });
        // 🔥 INICIALIZAR panel al cargar
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
      // PASO 1 → 2: Validar etapas seleccionadas
      const etapasSeleccionadas = document.querySelectorAll('.etapa-checkbox:checked:not(:disabled)').length;
      if (etapasSeleccionadas === 0) {
        alert('Debe seleccionar al menos una etapa');
        return;
      }
      
      console.log('🔥 WIZARD: Navegando Paso 1 → 2');
      window.WZ_STATE = window.WZ_STATE || {};
      window.WZ_STATE.currentStep = 2;
      window.gotoPaso?.(2);
      
      // 🎯 CARGAR TAREAS DEL CATÁLOGO para las etapas seleccionadas
      setTimeout(() => {
        const etapasSeleccionadas = document.querySelectorAll('.etapa-checkbox:checked:not(:disabled)');
        const slugs = Array.from(etapasSeleccionadas).map(cb => cb.getAttribute('data-slug') || cb.value);
        
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
      
      // Debug: contar todos los checkboxes disponibles
      const todosCheckboxes = document.querySelectorAll('.tarea-checkbox');
      const checkboxesChecked = document.querySelectorAll('.tarea-checkbox:checked');
      const checkboxesNoDisabled = document.querySelectorAll('.tarea-checkbox:not(:disabled)');
      const tareasSeleccionadas = document.querySelectorAll('.tarea-checkbox:checked:not(:disabled)');
      
      console.log(`🔍 WIZARD: Checkboxes encontrados:`, {
        todos: todosCheckboxes.length,
        checkeados: checkboxesChecked.length,
        noDisabled: checkboxesNoDisabled.length,
        seleccionadas: tareasSeleccionadas.length
      });
      
      // Debug: mostrar detalles de los primeros checkboxes
      if (todosCheckboxes.length > 0) {
        console.log(`🔍 WIZARD: Primer checkbox:`, {
          element: todosCheckboxes[0],
          classes: todosCheckboxes[0].className,
          checked: todosCheckboxes[0].checked,
          disabled: todosCheckboxes[0].disabled,
          value: todosCheckboxes[0].value,
          dataId: todosCheckboxes[0].getAttribute('data-id'),
          dataNombre: todosCheckboxes[0].getAttribute('data-nombre')
        });
      }
      
      if (tareasSeleccionadas.length === 0) {
        alert('Debe seleccionar al menos una tarea del catálogo');
        return;
      }
      
      // 🎯 CAPTURAR TAREAS EN WZ_STATE.tareasSel
      window.WZ_STATE = window.WZ_STATE || {};
      window.WZ_STATE.tareasSel = [];
      
      tareasSeleccionadas.forEach(checkbox => {
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