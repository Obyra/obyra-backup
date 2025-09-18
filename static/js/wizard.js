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
    const r = await fetch(`/obras/api/wizard-tareas/opciones?obra_id=${obraId}`, { credentials: 'include' });
    const j = await r.json();
    window.WZ_STATE.opciones = { unidades: j?.unidades || ['m2','m','m3','u','kg','h'], usuarios: j?.usuarios || [] };
  } catch {
    window.WZ_STATE.opciones = { unidades: ['m2','m','m3','u','kg','h'], usuarios: [] };
  }
  return window.WZ_STATE.opciones;
};

// 3) buildUsuarioSelect - Función helper - BLOQUE CANÓNICO
function buildUsuarioSelect(usuarios, asignadoId = null, index = 0) {
  let html = `<select name="rows[${index}][asignado]" class="form-select form-select-sm usuario-select">
    <option value="">— Seleccioná —</option>`;
  for (const u of usuarios) {
    const sel = (asignadoId && Number(asignadoId) === Number(u.id)) ? ' selected' : '';
    html += `<option value="${u.id}"${sel}>${u.nombre}</option>`;
  }
  html += `</select>`;
  return html;
}

// 3) window.renderPaso3(tareasSel) - BLOQUE CANÓNICO 
window.renderPaso3 = async function (tareasSel) {
  const modal = document.getElementById('wizardTareasModal');
  const tbody = modal.querySelector('#wizardStep3 #tablaDatosWizard tbody');
  if (!tbody) return;

  const obraId = Number(modal?.getAttribute('data-obra-id') || window.OBRA_ID || 0);
  const opts = await window.ensureOpciones(obraId);
  
  const unidadOpts = opts.unidades.map(u => `<option value="${u}">${u}</option>`).join('');

  tbody.innerHTML = (tareasSel || []).map((t, i) => `
    <tr data-i="${i}">
      <td>${t.etapa_slug||''}</td>
      <td>${t.nombre||''}</td>
      <td><input name="rows[${i}][inicio]"   class="form-control form-control-sm" type="date"></td>
      <td><input name="rows[${i}][fin]"      class="form-control form-control-sm" type="date"></td>
      <td><input name="rows[${i}][horas]"    class="form-control form-control-sm" type="number" min="0" step="0.5" value="8"></td>
      <td><input name="rows[${i}][cantidad]" class="form-control form-control-sm" type="number" min="0" step="0.01" value="1"></td>
      <td><select name="rows[${i}][unidad]"   class="form-select form-select-sm unidad-select">${unidadOpts}</select></td>
      <td>${buildUsuarioSelect(opts.usuarios, t.asignado_id, i)}</td>
      <td>
        <select name="rows[${i}][prioridad]" class="form-select form-select-sm">
          <option value="media" selected>Media</option>
          <option value="alta">Alta</option>
          <option value="baja">Baja</option>
        </select>
      </td>
    </tr>
  `).join('');

  window.enableNextStep3();
  window.ensureBackBtnStep3();
};

// 4) window.enableNextStep3() - BLOQUE CANÓNICO
window.enableNextStep3 = function () {
  const btn = document.getElementById('wizardBtnSiguiente');
  const rows = document.querySelectorAll('#wizardStep3 #tablaDatosWizard tbody tr').length;
  if (btn) {
    btn.disabled = rows === 0;
    btn.classList.toggle('disabled', rows === 0);
  }
};

// 5) window.gotoPaso(n) - BLOQUE CANÓNICO
window.gotoPaso = function (n) {
  const modal = document.getElementById('wizardTareasModal');
  console.log(`🔥 WIZARD: Navegando a paso ${n}`);
  
  // Soporta #wizardStepX o #wizardPasoX
  const target = modal.querySelector(`#wizardStep${n}`) || modal.querySelector(`#wizardPaso${n}`);
  if (target) {
    [...modal.querySelectorAll('[id^="wizardStep"], [id^="wizardPaso"]')].forEach(el => el.classList.add('d-none'));
    target.classList.remove('d-none');
    if (typeof updateWizardProgress === 'function') updateWizardProgress(n);
  }
};

// 6) window.ensureBackBtnStep3() - BLOQUE CANÓNICO
window.ensureBackBtnStep3 = function () {
  const modal = document.getElementById('wizardTareasModal');
  const footer = modal.querySelector('.modal-footer');
  if (!footer) return;

  let back = document.getElementById('wizardBtnAnteriorPaso3');
  if (!back) {
    back = document.createElement('button');
    back.id = 'wizardBtnAnteriorPaso3';
    back.type = 'button';
    back.className = 'btn btn-outline-secondary me-auto';
    back.textContent = 'Atrás';
    footer.insertBefore(back, footer.firstChild);
    back.addEventListener('click', (ev) => { 
      ev.preventDefault(); 
      window.gotoPaso(2); 
    });
  }
};

// 7) Progreso visual - BLOQUE CANÓNICO
window.updateWizardProgress = function(n) {
  const bars = document.querySelectorAll('.progress .progress-bar');
  bars.forEach(b => b.style.width = ({1: '25%', 2:'50%', 3:'75%', 4:'100%'}[n] || '0%'));
  
  document.querySelectorAll('[data-wizard-step]').forEach(el => {
    el.classList.toggle('active', Number(el.getAttribute('data-wizard-step')) === n);
  });
  
  const modal = document.getElementById('wizardTareasModal');
  if (modal) {
    modal.className = modal.className.replace(/\bwizard-step-\d+\b/g, '');
    modal.classList.add(`wizard-step-${n}`);
  }
  
  console.log(`[WZ] Progreso actualizado a paso ${n}`);
};

// =================== INTERCEPTOR ÚNICO PASO 2→3 ===================
function setupUniqueInterceptor() {
  const btn = resetButtonClean();
  if (!btn) return;
  
  const modal = document.getElementById('wizardTareasModal');
  
  // INTERCEPTOR ÚNICO - CON CLONACIÓN DE BOTÓN
  btn.addEventListener('click', (ev) => {
    const step2Visible = !!modal.querySelector('#wizardStep2:not(.d-none)');
    
    if (!step2Visible) {
      // Paso 1 → permitir flujo normal para applyCatalogAndAdvance
      const etapasSeleccionadas = [...modal.querySelectorAll('.etapa-checkbox:checked:not(:disabled)')].length;
      if (etapasSeleccionadas > 0) {
        ev.preventDefault();
        
        // Aplicar etapas seleccionadas
        const slugs = [...modal.querySelectorAll('.etapa-checkbox:checked:not(:disabled)')].map(cb => cb.dataset.slug).filter(Boolean);
        console.log(`🔥 WIZARD: Aplicando catálogo - ${slugs.length} etapas seleccionadas`);
        
        document.getElementById('btnAgregarEtapasSel')?.click(); 
        window.gotoPaso(2);
        
        const obraId = modal.dataset.obraId || document.querySelector('[data-obra-id]')?.dataset.obraId;
        if (obraId && typeof window.loadTareasWizard === 'function') {
          window.loadTareasWizard(obraId, slugs);
        }
      }
      return;
    }
    
    // Paso 2 → interceptar completamente
    ev.preventDefault();
    ev.stopPropagation();
    ev.stopImmediatePropagation();
    
    const sel = window.getSelPaso2();
    console.log(`🔥 WIZARD: Paso 2→3, selección:`, sel.length);
    
    if (sel.length === 0) return;
    
    window.WZ_STATE.tareasSel = sel;
    window.gotoPaso(3);
    window.renderPaso3(sel);
    if (typeof window.updateWizardProgress === 'function') window.updateWizardProgress(3);
  });
  
  console.log('✅ WIZARD: Interceptor único configurado');
}

// =================== COMPATIBILIDAD LEGACY ===================
window.connectPaso2Nav = setupUniqueInterceptor;

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
    // USAR EL ENDPOINT DEL CATÁLOGO (NO DB REAL)
    const res = await fetch('/obras/api/wizard-tareas/tareas', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      credentials: 'include',
      body: JSON.stringify({ obra_id: parseInt(obraId), etapas: slugs })
    });
    
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    
    const json = await res.json();
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
    console.log('🔥 WIZARD: Modal mostrado, configurando interceptor único');
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

// installFinishInterceptor - Interceptor del botón Finalizar
window.installFinishInterceptor = function() {
  const oldBtn = document.querySelector("#wizardBtnConfirmar");
  if (!oldBtn) return;
  
  const newBtn = oldBtn.cloneNode(true);
  newBtn.removeAttribute("data-bs-toggle");
  newBtn.removeAttribute("href");
  newBtn.removeAttribute("data-action");
  newBtn.removeAttribute("data-bs-dismiss");
  
  oldBtn.replaceWith(newBtn);
  
  newBtn.addEventListener("click", async (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    ev.stopImmediatePropagation?.();
    
    console.log('🔥 WIZARD: Finalizando wizard...');
    
    // Validaciones
    const payload = window.collectPaso3Payload();
    if (!payload.tareas || payload.tareas.length === 0) {
      alert('No hay tareas para crear');
      return;
    }
    
    const sinAsignar = payload.tareas.filter(t => !t.asignado_id || t.asignado_id === '');
    if (sinAsignar.length > 0) {
      const continuar = confirm(`${sinAsignar.length} tareas no tienen usuario asignado. ¿Continuar de todas formas?`);
      if (!continuar) return;
    }
    
    // Deshabilitar botón mientras procesa
    newBtn.disabled = true;
    newBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Creando...';
    
    try {
      const r = await fetch("/obras/api/wizard-tareas/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });
      
      const data = await r.json();
      
      if (data.ok) {
        console.log('✅ WIZARD: Tareas creadas exitosamente');
        window.gotoPaso(4);
        if (typeof window.updateWizardProgress === 'function') window.updateWizardProgress(4);
        
        // Mostrar mensaje de éxito
        const modal = document.getElementById('wizardTareasModal');
        const resumen = modal.querySelector('#resumenWizard');
        if (resumen) {
          resumen.innerHTML = `
            <div class="alert alert-success">
              <h5><i class="fas fa-check-circle text-success me-2"></i>¡Tareas creadas exitosamente!</h5>
              <p class="mb-0">Se crearon <strong>${payload.tareas.length} tareas</strong> en la obra.</p>
            </div>
          `;
        }
      } else {
        throw new Error(data.error || 'Error desconocido');
      }
      
    } catch (error) {
      console.error('❌ WIZARD: Error al crear tareas:', error);
      alert(`Error al finalizar: ${error.message}`);
    } finally {
      // Re-habilitar botón
      newBtn.disabled = false;
      newBtn.innerHTML = '<i class="fas fa-check me-1"></i>Crear Tareas';
    }
  }, { capture: true });
  
  console.log('✅ WIZARD: Interceptor de finalizar instalado');
};

// =================== AUTO-INSTALACIÓN ===================
document.addEventListener('shown.bs.modal', (ev) => {
  if (ev.target?.id === 'wizardTareasModal') {
    console.log('🔥 WIZARD: Modal mostrado, configurando interceptores');
    setupUniqueInterceptor();
    // Instalar interceptor de finalizar con un pequeño delay para asegurar que el DOM esté listo
    setTimeout(() => window.installFinishInterceptor(), 100);
  }
});

console.log('✅ WIZARD: Bloque canónico ÚNICO cargado - Sin duplicados');