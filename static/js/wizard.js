// 🧙‍♂️ WIZARD TAREAS - Sistema de creación masiva de tareas por etapas
// Versión ESTABILIZADA con event delegation y polyfills robustos

console.log('🧙‍♂️ WIZARD: Iniciando sistema estabilizado...');

// =================== POLYFILL GOTOPASO ===================
(function ensureGotoPaso(){
  // Mapea panes reales del DOM a números de paso (una vez)
  function mapDomSteps(){
    if (window.__WZ_STEP_MAP__) return window.__WZ_STEP_MAP__;
    const map = {};

    // candidatos a panes de pasos
    const panes = document.querySelectorAll(
      '.tab-pane,[role="tabpanel"],[data-wz-step],[id*="paso"],[id*="Paso"],[id*="step"],[id*="Step"]'
    );

    panes.forEach(p => {
      const id = p.id || '';
      let n = null;

      // 1) si ya viene data-wz-step, usarlo
      if (p.dataset.wzStep) n = Number(p.dataset.wzStep);

      // 2) intentar parsear el número de id: paso2, wizard-paso3, wizard-step4, etc.
      if (n == null) {
        const m = id.match(/(?:paso|Paso|step|Step)(\d+)/);
        if (m) n = Number(m[1]);
      }

      // 3) como fallback, si encontramos un heading "2. Tareas", etc.
      if (n == null) {
        const h = p.querySelector('h1,h2,h3,[data-step-title]');
        const t = h?.textContent || '';
        const m2 = t.match(/(\d)\s*[.)-]/);
        if (m2) n = Number(m2[1]);
      }

      if (n) {
        map[n] = map[n] || p;
        // Anotar para próximas veces
        p.dataset.wzStep = String(n);
      }
    });

    // También mapear triggers (tabs)
    const triggers = document.querySelectorAll('.nav-link,[data-bs-target],[href^="#"]');
    triggers.forEach(a => {
      const tgt = a.getAttribute('data-bs-target') || a.getAttribute('href') || '';
      const m = tgt.match(/(?:paso|Paso|step|Step)(\d+)/);
      if (m) {
        const n = Number(m[1]);
        map[n] = map[n] || document.querySelector(tgt);
      }
    });

    window.__WZ_STEP_MAP__ = map;
    return map;
  }

  window.gotoPaso = function(step){
    const map = mapDomSteps();

    // 1) probar con triggers de bootstrap
    const trigger = document.querySelector([
      `[data-bs-target="#wizard-paso${step}"]`,
      `[href="#wizard-paso${step}"]`,
      `[data-bs-target="#paso${step}"]`,
      `[href="#paso${step}"]`,
      `[data-bs-target="#wizardPaso${step}"]`,
      `[href="#wizardPaso${step}"]`,
      `[data-bs-target="#wizard-step${step}"]`,
      `[href="#wizard-step${step}"]`,
    ].join(','));

    if (trigger && window.bootstrap?.Tab) {
      window.bootstrap.Tab.getOrCreateInstance(trigger).show();
      return;
    }

    // 2) fallback: mostrar/ocultar panes usando el mapeo o selectores ampliados
    const pane = map[step] || document.querySelector(
      `#wizard-paso${step},#paso${step},#wizardPaso${step},#wizard-step${step},#step${step}`
    );

    if (pane) {
      const cont = pane.closest('.tab-content') || document;
      cont.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active','show'));
      pane.classList.add('active','show');
    } else {
      console.warn('gotoPaso: pane no encontrado', step);
    }
  };
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

// FINALIZAR: Paso 3 -> 4
if (!window.__WZ_FINISH_INSTALLED__) {
  window.__WZ_FINISH_INSTALLED__ = true;
  document.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('#wizardBtnConfirmar, #wizard-finish, [data-action="finish"]');
    if (!btn) return;
    ev.preventDefault(); ev.stopPropagation(); ev.stopImmediatePropagation?.();

    console.log('🎯 WIZARD: Finalizando (event delegation)...');
    
    const payload = window.collectPaso3Payload?.();
    if (!payload?.tareas?.length) {
      alert('No hay tareas para crear');
      return;
    }
    
    btn.disabled = true;
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Creando...';
    
    try {
      const r = await fetch(api('obras/api/wizard-tareas/create'), {
        method: 'POST', 
        headers: {'Content-Type':'application/json'}, 
        credentials:'same-origin',
        body: JSON.stringify(payload)
      });
      const j = await r.json();
      if (!r.ok || !j.ok) { 
        console.error(j); 
        alert(j.error || 'No se pudo finalizar'); 
        return; 
      }

      console.log('✅ WIZARD: Tareas creadas, navegando a Paso 4');
      // anti-rebote corto
      window.__WZ_NAV_LOCK_UNTIL__ = Date.now() + 2000;
      window.gotoPaso?.(4);
      
    } catch (error) {
      console.error('❌ WIZARD: Error:', error);
      alert(`Error: ${error.message}`);
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalHTML;
    }
  }, { capture: true });
}

// CONFIRMAR: Paso 4 -> cerrar modal
if (!window.__WZ_CONFIRM_INSTALLED__) {
  window.__WZ_CONFIRM_INSTALLED__ = true;
  document.addEventListener('click', (ev) => {
    const btn = ev.target.closest('#wizardBtnCerrar, #wizardBtnFin, #wizard-confirm, [data-action="confirm"]');
    if (!btn) return;
    ev.preventDefault(); ev.stopPropagation(); ev.stopImmediatePropagation?.();

    console.log('🎯 WIZARD: Confirmando - cerrando modal...');
    const modalEl = document.querySelector('#wizardTareasModal, #wizard-modal');
    if (modalEl) { 
      try { 
        bootstrap.Modal.getOrCreateInstance(modalEl).hide(); 
        // Opcional: refrescar para mostrar nuevas tareas
        setTimeout(() => window.location.reload(), 300);
      } catch {} 
    }
  }, { capture: true });
}

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
                           data-slug="${etapa.slug}" 
                           data-nombre="${etapa.nombre}"
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
  
  console.log('✅ WIZARD: Eventos de catálogo rebindeados');
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
  
  // Habilitar/deshabilitar botón siguiente
  const btnSiguiente = document.getElementById('wizardBtnSiguiente');
  if (btnSiguiente) {
    btnSiguiente.disabled = count === 0;
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

// 🔥 Actualizar contador cuando cambie cualquier checkbox
document.addEventListener('change', (e) => {
  if (e.target.matches('.etapa-checkbox')) {
    updateSelectionCounter();
  }
});

// 🔥 EXPONER FUNCIONES AL GLOBAL
window.cargarCatalogoEtapas = cargarCatalogoEtapas;
window.rebindCatalogEvents = rebindCatalogEvents;
window.updateSelectionCounter = updateSelectionCounter;

// =================== ESTADO GLOBAL DEL WIZARD ===================
window.WZ_STATE = window.WZ_STATE || { tareasSel: [] };

// Opciones/equipos
window.ensureOpciones = async function (obraId) {
  if (window.WZ_STATE.opciones) return window.WZ_STATE.opciones;

  try {
    const data = await fetchJSON(api(`obras/api/wizard-tareas/opciones?obra_id=${obraId}`));
    window.WZ_STATE.opciones = data;
    return data;
    
  } catch (error) {
    console.error('❌ WIZARD: Error cargando opciones:', error);
    return { unidades: ['h'], equipo: [] };
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
  const equipo = opciones.equipo || [];

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
  
  if (spin) spin.classList.remove('d-none');
  if (list) list.innerHTML = '';
  
  try {
    // USAR EL ENDPOINT DEL CATÁLOGO (NO DB REAL) - Ruta absoluta
    const json = await fetchJSON(api(`obras/api/wizard-tareas/tareas?obra_id=${obraId}&etapas=${encodeURIComponent(JSON.stringify(slugs))}`), {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ obra_id: parseInt(obraId), etapas: slugs })
    });
    
    const tareas = json.tareas_catalogo || json.tareas || json.data || [];
    
    if (spin) spin.classList.add('d-none');
    
    if (list) {
      list.innerHTML = tareas.length
        ? `<div class="mb-3">
             <h6 class="text-primary">📋 Plantillas disponibles (${tareas.length}):</h6>
             <div class="row">${
               tareas.map(t => `
                 <div class="col-md-6 mb-2">
                   <div class="form-check">
                     <input class="form-check-input tarea-checkbox" type="checkbox" 
                            data-id="${t.id}" 
                            data-nombre="${t.nombre}"
                            data-etapa="${t.etapa_slug}"
                            id="tarea-${t.id}">
                     <label class="form-check-label" for="tarea-${t.id}">
                       <strong>${t.nombre}</strong>
                       ${t.descripcion ? `<br><small class="text-muted">${t.descripcion}</small>` : ''}
                       <small class="text-info d-block">⏱️ ${t.horas || 0}h estimadas</small>
                     </label>
                   </div>
                 </div>
               `).join('')
             }</div>
           </div>`
        : '<div class="text-muted text-center p-4">📝 No hay plantillas disponibles para las etapas seleccionadas.</div>';
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

// =================== NAVEGACIÓN PASO 1 → 2 ===================
// Interceptor único para botón "Siguiente" (Paso 1 → 2)
function setupUniqueInterceptor() {
  const btnSiguiente = document.getElementById('wizardBtnSiguiente');
  if (!btnSiguiente || btnSiguiente.dataset.wizardBound) return;
  
  btnSiguiente.dataset.wizardBound = 'true';
  
  btnSiguiente.addEventListener('click', (ev) => {
    ev.preventDefault();
    
    const etapasSeleccionadas = document.querySelectorAll('.etapa-checkbox:checked:not(:disabled)').length;
    if (etapasSeleccionadas === 0) {
      alert('Debe seleccionar al menos una etapa');
      return;
    }
    
    console.log('🔥 WIZARD: Navegando Paso 1 → 2');
    window.gotoPaso?.(2);
  });
  
  console.log('✅ WIZARD: Interceptor Paso 1→2 configurado');
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