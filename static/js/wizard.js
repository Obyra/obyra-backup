// 🧙‍♂️ WIZARD TAREAS - Sistema de creación masiva de tareas por etapas
// Versión con EVENT DELEGATION para robustez ante re-renderizado del DOM

console.log('🧙‍♂️ WIZARD: Iniciando sistema con event delegation...');

// =================== PREFIJO Y UTILIDADES ===================
const PREF = window.PREFIX || '';

// Helper para forzar rutas absolutas
const api = (p) => p.startsWith('/') ? p : `/${p}`;

// Helper para fetch con manejo robusto de errores y HTML
async function fetchJSON(url, opts = {}) {
  try {
    const r = await fetch(url, { credentials: 'same-origin', ...opts });
    const ctype = r.headers.get('content-type') || '';
    const text = await r.text();

    if (!r.ok) {
      throw new Error(
        ctype.includes('application/json')
          ? (JSON.parse(text).error || `HTTP ${r.status}`)
          : `HTTP ${r.status} (no JSON): ${text.slice(0,120)}`
      );
    }
    
    if (!ctype.includes('application/json')) {
      throw new Error(`Respuesta no-JSON del servidor: ${text.slice(0,120)}`);
    }
    
    return JSON.parse(text);
  } catch (error) {
    console.error('❌ WIZARD: Error en fetchJSON:', error);
    throw error;
  }
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
    
    // 🔥 Usar ruta absoluta para evitar 404
    const url = api(`obras/api/wizard-tareas/etapas?obra_id=${obraId}`);
    const json = await fetchJSON(url);
    
    // fetchJSON ya maneja errores HTTP
    
    // 🔥 Usar las claves correctas
    const catalogo = Array.isArray(json) ? json : (json.etapas_catalogo || []);
    const creadas = new Set((json.etapas_creadas || []).map(e => e.slug || e.id));
    
    console.log('📦 WIZARD: Catálogo recibido:', { catalogo: catalogo.length, creadas: creadas.size });
    console.log('🔍 WIZARD: Etapas creadas:', Array.from(creadas));
    
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

// 🔥 ESTADO GLOBAL DEL WIZARD
window.WZ_STATE = window.WZ_STATE || { tareasSel: [] };

// =================== BLOQUE CANÓNICO ÚNICO ===================
// Eliminar listeners viejos clonando y reemplazando el botón
function resetButtonClean() {
  const oldBtn = document.getElementById('wizardBtnSiguiente');
  if (!oldBtn) return null;
  
  const newBtn = oldBtn.cloneNode(true);
  oldBtn.parentNode.replaceChild(newBtn, oldBtn);
  
  // Limpiar marcadores legacy
  delete newBtn.dataset.bound;
  delete newBtn.dataset.boundPaso2;
  delete newBtn.dataset.boundStep2;
  
  console.log('🔥 WIZARD: Botón clonado, listeners viejos eliminados');
  return newBtn;
}

// 1) window.getSelPaso2(modal) - BLOQUE CANÓNICO
window.getSelPaso2 = function(modal) {
  const m = modal || document.getElementById('wizardTareasModal');
  return [...m.querySelectorAll('#wizardStep2 input[type="checkbox"]:checked')].map((cb, i) => ({
    id: cb.dataset.id || cb.value || String(i + 1),
    nombre: (cb.closest('.form-check')?.querySelector('label')?.textContent || `Tarea ${i+1}`).trim(),
    etapa_slug: cb.dataset.etapa || '',
    etapa_id: null  // Las plantillas no tienen etapa_id hasta ser creadas
  }));
};

// 2) window.ensureOpciones(obra_id) - BLOQUE CANÓNICO  
window.ensureOpciones = async function (obraId) {
  if (window.WZ_STATE.opciones) return window.WZ_STATE.opciones;

  try {
    const url = api(`obras/api/wizard-tareas/opciones?obra_id=${obraId}`);
    const data = await fetchJSON(url);
    window.WZ_STATE.opciones = data;
    return data;
    
  } catch (error) {
    console.error('❌ WIZARD: Error cargando opciones:', error);
    return { unidades: ['h'], equipo: [] };
  }
};

// 3) window.populatePaso3() - BLOQUE CANÓNICO
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

// 4) window.applyCatalogAndAdvance() - BLOQUE CANÓNICO
window.applyCatalogAndAdvance = function() {
  const modal = document.getElementById('wizardTareasModal');
  const etapasSeleccionadas = document.querySelectorAll('.etapa-checkbox:checked:not(:disabled)').length;
  
  if (etapasSeleccionadas === 0) {
    alert('Debe seleccionar al menos una etapa');
    return;
  }

  // Avanzar al paso 2 Y cargar tareas del catálogo
  const slugs = [...modal.querySelectorAll('.etapa-checkbox:checked:not(:disabled)')].map(cb => cb.dataset.slug).filter(Boolean);
  console.log(`🔥 WIZARD: Aplicando catálogo - ${slugs.length} etapas seleccionadas`);
  
  document.getElementById('btnAgregarEtapasSel')?.click(); 
  window.gotoPaso(2);
  
  const obraId = modal.dataset.obraId || document.querySelector('[data-obra-id]')?.dataset.obraId;
  if (obraId && typeof window.loadTareasWizard === 'function') {
    window.loadTareasWizard(obraId, slugs);
  }
};

// 5) setupUniqueInterceptor - INSTALADOR ÚNICO
function setupUniqueInterceptor() {
  const newBtn = resetButtonClean();
  if (!newBtn) return;

  // Marcar como configurado para evitar doble binding
  if (newBtn.dataset.bound) return;
  newBtn.dataset.bound = 'true';

  newBtn.addEventListener('click', (ev) => {
    ev.preventDefault(); 
    window.gotoPaso(2); 
  });
  
  console.log('✅ WIZARD: Interceptor único configurado');
}

// =================== FUNCIÓN CATÁLOGO ===================
// Función para obtener tareas del catálogo local (alternativa)
window.getCatalogTasksFor = function(selectedEtapas) {
  // Si tenemos catálogo cargado en memoria, usarlo
  const map = window.WZ_CATALOGO?.tareas_por_etapa || {};
  const out = [];
  
  for (const etapa of selectedEtapas) {
    const lista = map[etapa] || [];
    lista.forEach((t, idx) => out.push({ 
      ...t, 
      id: `${etapa}-${idx+1}`,
      etapa_slug: etapa,
      _source: 'catalog' 
    }));
  }
  
  return out;
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
    const url = api('obras/api/wizard-tareas/tareas');
    const json = await fetchJSON(url, {
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

// =================== INICIALIZACIÓN ===================
document.addEventListener('shown.bs.modal', (ev) => {
  if (ev.target?.id === 'wizardTareasModal') {
    console.log('🔥 WIZARD: Modal abierto, configurando interceptor único');
    setupUniqueInterceptor();
  }
});

// =================== FUNCIONES PASO 3 → FINALIZAR ===================

// collectPaso3Payload - Recopilar datos del Paso 3
window.collectPaso3Payload = function() {
  const modal = document.getElementById('wizardTareasModal');
  const rows = [...modal.querySelectorAll('#wizardStep3 #tablaDatosWizard tbody tr')];
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

// =================== EVENT DELEGATION INTERCEPTORS ===================

// 1) Delegado para botón FINALIZAR (Paso 3 → Paso 4)
if (!window.__WZ_FINISH_INSTALLED__) {
  window.__WZ_FINISH_INSTALLED__ = true;
  document.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('#wizardBtnConfirmar, #wizard-finish, [data-action="finish"]');
    if (!btn) return;
    
    ev.preventDefault();
    ev.stopPropagation();
    ev.stopImmediatePropagation?.();
    
    console.log('🎯 WIZARD: Finalizando (delegado) - creando tareas...');
    
    // VALIDACIONES
    const payload = window.collectPaso3Payload();
    if (!payload.tareas || payload.tareas.length === 0) {
      alert('No hay tareas para crear');
      return;
    }
    
    // Opcional: confirmar si hay tareas sin asignar
    const sinAsignar = payload.tareas.filter(t => !t.asignado_usuario_id);
    if (sinAsignar.length > 0) {
      const continuar = confirm(`${sinAsignar.length} tareas no tienen usuario asignado. ¿Continuar?`);
      if (!continuar) return;
    }
    
    // Deshabilitar botón
    btn.disabled = true;
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Creando...';
    
    try {
      const url = api('obras/api/wizard-tareas/create');
      const data = await fetchJSON(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      
      if (!data.ok) {
        throw new Error(data.error || 'Error desconocido');
      }
      
      console.log('✅ WIZARD: Tareas creadas, avanzando a Paso 4');
      
      // LOCK anti-rebote por 2 segundos y avanzar
      window.__WZ_NAV_LOCK_UNTIL__ = Date.now() + 2000;
      window.gotoPaso(4);
      
    } catch (error) {
      console.error('❌ WIZARD: Error al finalizar:', error);
      alert(`No se pudo finalizar: ${error.message}`);
    } finally {
      // Restaurar botón
      btn.disabled = false;
      btn.innerHTML = originalHTML;
    }
  }, { capture: true });
  
  console.log('✅ WIZARD: Delegado FINALIZAR instalado');
}

// 2) Delegado para botón CONFIRMAR (Paso 4 → Cerrar Modal)
if (!window.__WZ_CONFIRM_INSTALLED__) {
  window.__WZ_CONFIRM_INSTALLED__ = true;
  document.addEventListener('click', (ev) => {
    const btn = ev.target.closest('#wizardBtnCerrar, #wizard-confirm, #wizardBtnFin, [data-action="confirm"]');
    if (!btn) return;
    
    ev.preventDefault();
    ev.stopPropagation();
    ev.stopImmediatePropagation?.();
    
    console.log('🎯 WIZARD: Confirmando (delegado) - cerrando modal...');
    
    const modalEl = document.querySelector('#wizardTareasModal, #wizard-modal');
    if (modalEl) {
      try {
        bootstrap.Modal.getOrCreateInstance(modalEl).hide();
        console.log('✅ WIZARD: Modal cerrado exitosamente');
        
        // Opcional: refrescar para mostrar las nuevas tareas
        setTimeout(() => {
          window.location.reload();
        }, 300);
        
      } catch (error) {
        console.error('❌ WIZARD: Error cerrando modal:', error);
      }
    }
  }, { capture: true });
  
  console.log('✅ WIZARD: Delegado CONFIRMAR instalado');
}

// 3) Neutralizar rebotes a Paso 2 (tabs/anchors legacy)
if (!window.__WZ_GUARD_INSTALLED__) {
  window.__WZ_GUARD_INSTALLED__ = true;
  
  // Bloquea clicks a anchors del paso 2 mientras esté activo el lock
  document.addEventListener('click', (ev) => {
    const a = ev.target.closest('a[href="#paso2"], a[href="#wizardPaso2"]');
    if (!a) return;
    
    const lock = window.__WZ_NAV_LOCK_UNTIL__ || 0;
    if (Date.now() < lock) {
      ev.preventDefault();
      ev.stopPropagation();
      ev.stopImmediatePropagation?.();
      console.log('🚫 WIZARD: Click a Paso 2 bloqueado (lock activo)');
    }
  }, { capture: true });
  
  // Limpia cambios de hash a paso2 durante el lock
  window.addEventListener('hashchange', (e) => {
    const lock = window.__WZ_NAV_LOCK_UNTIL__ || 0;
    if (Date.now() < lock && /paso2/i.test(location.hash)) {
      console.log('🚫 WIZARD: Hashchange a Paso 2 bloqueado (lock activo)');
      history.replaceState(null, '', '#');
      e.stopImmediatePropagation?.();
    }
  }, { capture: true });
  
  console.log('✅ WIZARD: Guards anti-rebote instalados');
}

console.log('✅ WIZARD: Sistema con EVENT DELEGATION cargado - Flujo Paso1→2→3→4→Cerrar');