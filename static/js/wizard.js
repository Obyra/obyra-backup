/*
 * Wizard de creación masiva de tareas por etapas
 * Implementación simple y robusta que mantiene el estado en window.WZ_STATE
 * y expone los helpers esperados por los templates legacy.
 */

function initWizard() {
  const modal = document.getElementById('wizardTareasModal');
  if (!modal) {
    console.debug('Wizard tareas: modal no encontrado, se difiere la inicialización');
    return;
  }

  const obraId = Number(modal.getAttribute('data-obra-id')) || Number(window.obraId) || 0;
  if (!obraId) {
    console.warn('Wizard tareas: obraId no disponible, no se inicializa el wizard');
    return;
  }

  const stepPanes = Array.from(modal.querySelectorAll('.tab-pane'));
  const btnPrev = modal.querySelector('#wizardBtnAnterior');
  const btnNext = modal.querySelector('#wizardBtnSiguiente');
  const btnConfirm = modal.querySelector('#wizardBtnConfirmar');
  const btnFinish = modal.querySelector('#wizardBtnFin');
  const progressBar = modal.querySelector('#wizardProgressBar');
  const resumenContainer = modal.querySelector('#resumenWizard');
  const tareasSeleccionadasPanel = modal.querySelector('#tareas-seleccionadas-list');
  const tablaPaso3 = modal.querySelector('#tablaDatosWizard tbody');

  const stepCount = stepPanes.length || 4;

  const state = {
    obraId,
    step: 1,
    catalogo: [],
    etapasCreadas: [],
    selectedEtapas: new Map(), // key -> {catalogId, slug, nombre}
    tareasDisponibles: [],
    selectedTasks: [],
    opciones: null,
    result: null,
    submitting: false,
  };

  window.WZ_STATE = window.WZ_STATE || {};
  window.WZ_STATE.etapasSel = window.WZ_STATE.etapasSel || new Set();
  window.WZ_STATE.tareasSel = window.WZ_STATE.tareasSel || [];

  const metaBySlug = new Map();
  const metaById = new Map();

  function normalizeCatalogId(value) {
    if (value == null || value === '' || value === 'null') {
      return null;
    }
    const asNumber = Number(value);
    if (Number.isFinite(asNumber)) {
      return String(asNumber);
    }
    return String(value).trim() || null;
  }

  function resolveEtapaMeta({ slug, catalogId, nombre }) {
    const slugKey = (slug || '').trim();
    const catalogKey = normalizeCatalogId(catalogId);
    const nombreKey = (nombre || '').trim().toLowerCase();

    if (slugKey && metaBySlug.has(slugKey)) {
      return metaBySlug.get(slugKey);
    }
    if (catalogKey && metaById.has(catalogKey)) {
      return metaById.get(catalogKey);
    }

    const selectedMeta = Array.from(state.selectedEtapas.values()).find((meta) => {
      const metaSlug = (meta.slug || '').trim();
      const metaId = normalizeCatalogId(meta.catalogId);
      const metaNombre = (meta.nombre || '').trim().toLowerCase();
      return (slugKey && metaSlug === slugKey)
        || (catalogKey && metaId === catalogKey)
        || (nombreKey && metaNombre && metaNombre === nombreKey);
    });

    if (selectedMeta) {
      const resolvedSlug = (selectedMeta.slug || slugKey || '').trim();
      const resolvedNombre = selectedMeta.nombre || nombre || '';
      const resolvedId = normalizeCatalogId(selectedMeta.catalogId) || catalogKey || null;
      const metaObj = { id: resolvedId, slug: resolvedSlug || null, nombre: resolvedNombre };
      if (resolvedSlug && !metaBySlug.has(resolvedSlug)) {
        metaBySlug.set(resolvedSlug, metaObj);
      }
      if (resolvedId && !metaById.has(resolvedId)) {
        metaById.set(resolvedId, metaObj);
      }
      return metaObj;
    }

    if (slugKey || catalogKey || nombre) {
      const metaObj = {
        id: catalogKey,
        slug: slugKey || null,
        nombre: nombre || '',
      };
      if (slugKey && !metaBySlug.has(slugKey)) {
        metaBySlug.set(slugKey, metaObj);
      }
      if (catalogKey && !metaById.has(catalogKey)) {
        metaById.set(catalogKey, metaObj);
      }
      return metaObj;
    }

    return { id: null, slug: null, nombre: nombre || '' };
  }

  function fetchJSON(url, options) {
    return fetch(url, { credentials: 'same-origin', ...options })
      .then(async (response) => {
        const text = await response.text();
        const contentType = response.headers.get('content-type') || '';
        const asJSON = contentType.includes('application/json') ? JSON.parse(text || '{}') : null;
        if (!response.ok) {
          const errorMessage = asJSON?.error || `HTTP ${response.status}`;
          throw new Error(errorMessage);
        }
        if (!asJSON) {
          throw new Error('La respuesta del servidor no es JSON');
        }
        return asJSON;
      });
  }

  function setStep(step) {
    state.step = step;
    window.WZ_STATE.currentStep = step;

    stepPanes.forEach((pane, index) => {
      const isActive = index === (step - 1);
      pane.classList.toggle('show', isActive);
      pane.classList.toggle('active', isActive);
      pane.setAttribute('aria-hidden', String(!isActive));
      if (isActive) {
        pane.setAttribute('tabindex', '-1');
        setTimeout(() => {
          if (typeof pane.focus === 'function') {
            try {
              pane.focus({ preventScroll: true });
            } catch (err) {
              console.debug('No se pudo enfocar el paso activo', err);
            }
          }
        }, 0);
      } else {
        pane.removeAttribute('tabindex');
      }
    });

    if (progressBar) {
      const progress = Math.min(100, Math.max(0, (step / stepCount) * 100));
      progressBar.style.width = `${progress}%`;
    }

    if (btnPrev) {
      btnPrev.style.display = step > 1 && step < 4 ? 'inline-flex' : 'none';
    }
    if (btnNext) {
      btnNext.style.display = step < 4 ? 'inline-flex' : 'none';
      btnNext.disabled = step === 1 && state.selectedEtapas.size === 0;
    }
    if (btnConfirm) {
      btnConfirm.style.display = step === 4 && !state.submitting ? 'inline-flex' : 'none';
      btnConfirm.disabled = !!state.submitting;
    }
    if (btnFinish) {
      btnFinish.style.display = state.result ? 'inline-flex' : 'none';
    }

    actualizarPasosVisuales();
  }

  function actualizarPasosVisuales() {
    modal.querySelectorAll('.wizard-step').forEach((el) => {
      const paso = Number(el.getAttribute('data-step'));
      if (paso < state.step) {
        el.classList.add('text-success');
      } else {
        el.classList.remove('text-success');
      }
      if (paso === state.step) {
        el.classList.add('fw-bold');
      } else {
        el.classList.remove('fw-bold');
      }
    });
  }

  function renderCatalog(catalogo, creadas) {
    const container = modal.querySelector('#catalogoEtapas');
    if (!container) {
      return;
    }

    metaBySlug.clear();
    metaById.clear();

    const creadasIds = new Set((creadas || []).map((et) => String(et.id)));
    const creadasSlugs = new Set((creadas || []).map((et) => et.slug).filter(Boolean));

    const cards = catalogo.map((etapa) => {
      const id = etapa.id != null ? String(etapa.id) : '';
      const catalogId = normalizeCatalogId(id);
      const slug = etapa.slug || '';
      const nombre = etapa.nombre || '';
      const descripcion = etapa.descripcion || '';
      const yaCreada = creadasIds.has(id) || (slug && creadasSlugs.has(slug));

      if (slug) {
        metaBySlug.set(slug, { id: catalogId, slug, nombre });
      }
      if (catalogId) {
        metaById.set(catalogId, { id: catalogId, slug, nombre });
      }

      const checked = yaCreada || window.WZ_STATE.etapasSel.has(id) || window.WZ_STATE.etapasSel.has(slug);
      const disabled = yaCreada;
      const badgeClass = yaCreada ? 'bg-success' : 'bg-primary';
      const badgeText = yaCreada ? 'Agregada' : 'Disponible';

      return `
        <div class="col-md-6 mb-3">
          <div class="card ${yaCreada ? 'border-success' : ''}">
            <div class="card-body p-3">
              <div class="form-check">
                <input class="form-check-input etapa-checkbox" type="checkbox"
                       id="catalogEtapa${id}"
                       data-etapa-id="${id}"
                       data-etapa-slug="${slug}"
                       data-etapa-nombre="${nombre.replace(/"/g, '&quot;')}"
                       ${checked ? 'checked' : ''}
                       ${disabled ? 'disabled' : ''}>
                <label class="form-check-label w-100" for="catalogEtapa${id}">
                  <div class="d-flex justify-content-between align-items-start">
                    <div>
                      <h6 class="mb-1 ${yaCreada ? 'text-success' : ''}">📋 ${nombre}</h6>
                      <p class="text-muted small mb-0">${descripcion}</p>
                    </div>
                    <span class="badge ${badgeClass}">${badgeText}</span>
                  </div>
                </label>
              </div>
            </div>
          </div>
        </div>
      `;
    }).join('');

    container.innerHTML = cards || '<div class="col-12 text-center py-4 text-muted">No hay etapas disponibles.</div>';

    bindCatalogEvents();
    rehydrateChecksFromState();
    updateEtapasBadge();
  }

  async function loadCatalog() {
    const spinner = modal.querySelector('#catalogoEtapas .spinner-border');
    if (spinner) {
      spinner.classList.remove('d-none');
    }

    const data = await fetchJSON(`/obras/api/wizard-tareas/etapas?obra_id=${obraId}`);
    state.catalogo = data.etapas_catalogo || [];
    state.etapasCreadas = data.etapas_creadas || [];

    renderCatalog(state.catalogo, state.etapasCreadas);
  }

  function updateEtapasSeleccionadas() {
    state.selectedEtapas.clear();
    window.WZ_STATE.etapasSel.clear();

    modal.querySelectorAll('.etapa-checkbox:checked').forEach((checkbox) => {
      const id = normalizeCatalogId(checkbox.dataset.etapaId || '');
      const slug = checkbox.dataset.etapaSlug || '';
      const nombre = checkbox.dataset.etapaNombre || '';
      const key = slug || id;
      if (!key) {
        return;
      }
      state.selectedEtapas.set(key, { catalogId: id || null, slug: slug || null, nombre });
      window.WZ_STATE.etapasSel.add(key);
    });

    window.WIZARD = window.WIZARD || {};
    window.WIZARD.etapas_seleccionadas = Array.from(state.selectedEtapas.values());

    updateEtapasBadge();
  }

  async function loadTareas() {
    const slugs = Array.from(state.selectedEtapas.values())
      .map((meta) => meta.slug)
      .filter(Boolean);

    if (!slugs.length) {
      throw new Error('Debés seleccionar al menos una etapa del catálogo');
    }

    const spinner = modal.querySelector('#wizardSpinnerTareas');
    const list = modal.querySelector('#wizardListaTareas');
    if (spinner) {
      spinner.classList.remove('d-none');
    }
    if (list) {
      list.innerHTML = '';
    }

    const data = await fetchJSON('/obras/api/wizard-tareas/tareas', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ obra_id: obraId, etapas: slugs }),
    });

    const tareas = data.tareas_catalogo || [];
    state.tareasDisponibles = tareas;
    renderTareas(tareas);

    if (spinner) {
      spinner.classList.add('d-none');
    }
  }

  function renderTareas(tareas) {
    const list = modal.querySelector('#wizardListaTareas');
    if (!list) {
      return;
    }

    if (!Array.isArray(tareas) || !tareas.length) {
      list.innerHTML = '<div class="text-muted text-center py-4">No hay tareas disponibles para las etapas seleccionadas.</div>';
      window.WZ_STATE.tareasSel = [];
      state.selectedTasks = [];
      updateTaskSelectionPanel();
      return;
    }

    const html = tareas.map((tarea, index) => {
      const slug = tarea.etapa_slug || '';
      const meta = resolveEtapaMeta({
        slug,
        catalogId: tarea.catalogo_id || tarea.catalogoId || tarea.etapa_id,
        nombre: tarea.etapa_nombre,
      });
      const nombreEtapa = meta.nombre || tarea.etapa_nombre || slug || 'Etapa';
      const id = tarea.id ? String(tarea.id) : `${slug}-${index}`;
      const catalogAttr = meta.id || '';
      return `
        <div class="col-md-6 mb-2">
          <div class="form-check">
            <input class="form-check-input tarea-checkbox" type="checkbox" id="tarea-${id}"
                   data-tarea-id="${id}"
                   data-tarea-nombre="${tarea.nombre || ''}"
                   data-etapa-slug="${slug}"
                   data-etapa-nombre="${nombreEtapa}"
                   data-etapa-id="${catalogAttr}"
                   data-unidad="${tarea.unidad_default || tarea.unidad || 'h'}"
                   data-horas="${tarea.horas || ''}">
            <label class="form-check-label" for="tarea-${id}">
              <strong>${tarea.nombre || 'Tarea sin nombre'}</strong>
              <div class="text-muted small">${nombreEtapa}</div>
            </label>
          </div>
        </div>
      `;
    }).join('');

    list.innerHTML = `<div class="row">${html}</div>`;

    list.querySelectorAll('.tarea-checkbox').forEach((checkbox) => {
      checkbox.addEventListener('change', handleTaskSelectionChange);
    });

    window.WZ_STATE.tareasSel = [];
    state.selectedTasks = [];
    updateTaskSelectionPanel();
  }

  function handleTaskSelectionChange() {
    const seleccionadas = [];
    modal.querySelectorAll('.tarea-checkbox:checked').forEach((checkbox) => {
      const slug = checkbox.dataset.etapaSlug || '';
      const catalogId = normalizeCatalogId(checkbox.dataset.etapaId || '');
      const meta = resolveEtapaMeta({
        slug,
        catalogId,
        nombre: checkbox.dataset.etapaNombre || '',
      });
      seleccionadas.push({
        nombre: checkbox.dataset.tareaNombre || '',
        etapa_slug: slug || meta.slug || null,
        etapa_nombre: checkbox.dataset.etapaNombre || meta.nombre || '',
        unidad: checkbox.dataset.unidad || 'h',
        horas: checkbox.dataset.horas ? Number(checkbox.dataset.horas) : null,
        catalogo_id: meta.id ? normalizeCatalogId(meta.id) : null,
      });
    });

    state.selectedTasks = seleccionadas;
    window.WZ_STATE.tareasSel = seleccionadas;
    window.WIZARD = window.WIZARD || {};
    window.WIZARD.tareas_seleccionadas = seleccionadas;
    updateTaskSelectionPanel();
  }

  function updateTaskSelectionPanel() {
    if (!tareasSeleccionadasPanel) {
      return;
    }

    if (!state.selectedTasks.length) {
      tareasSeleccionadasPanel.innerHTML = '<p class="text-muted">Ninguna tarea seleccionada</p>';
    } else {
      const items = state.selectedTasks.map((task) => `
        <div class="small mb-1">${task.nombre}<br><span class="text-muted">${task.etapa_nombre || task.etapa_slug || ''}</span></div>
      `).join('');
      tareasSeleccionadasPanel.innerHTML = `
        <div class="fw-semibold mb-2">Tareas seleccionadas (${state.selectedTasks.length})</div>
        ${items}
      `;
    }
  }

  function ensureOpciones() {
    if (state.opciones) {
      return Promise.resolve(state.opciones);
    }
    return fetchJSON(`/obras/api/wizard-tareas/opciones?obra_id=${obraId}`)
      .then((data) => {
        state.opciones = {
          unidades: data.unidades || ['h'],
          usuarios: data.usuarios || [],
        };
        return state.opciones;
      })
      .catch((error) => {
        console.error('No se pudieron cargar las opciones del wizard', error);
        state.opciones = { unidades: ['h'], usuarios: [] };
        return state.opciones;
      });
  }

  function populatePaso3() {
    if (!tablaPaso3) {
      return Promise.resolve();
    }
    if (!state.selectedTasks.length) {
      tablaPaso3.innerHTML = '';
      return Promise.resolve();
    }

    return ensureOpciones().then((opciones) => {
      const unidades = opciones.unidades || ['h'];
      const usuarios = opciones.usuarios || [];

      const rows = state.selectedTasks.map((task, index) => {
        const meta = resolveEtapaMeta({
          slug: task.etapa_slug,
          catalogId: task.catalogo_id,
          nombre: task.etapa_nombre,
        });
        const etapaId = meta?.id || '';
        const slug = task.etapa_slug || meta?.slug || '';
        const etapaNombre = task.etapa_nombre || meta?.nombre || '';
        const horas = task.horas && Number(task.horas) > 0 ? Number(task.horas) : 8;

        const unidadesOpts = unidades.map((unidad) => `
          <option value="${unidad}" ${unidad === (task.unidad || 'h') ? 'selected' : ''}>${unidad}</option>
        `).join('');

        const usuariosOpts = [`<option value="">— Seleccioná —</option>`, ...usuarios.map((user) => `
          <option value="${user.id}">${user.nombre}</option>
        `)].join('');

        return `
          <tr data-index="${index}" data-etapa-slug="${slug}" data-etapa-id="${etapaId || ''}" data-etapa-nombre="${etapaNombre}">
            <td class="small text-muted">${etapaNombre || slug || 'Sin etapa'}</td>
            <td class="fw-semibold tarea-nombre">${task.nombre}</td>
            <td><input type="date" class="form-control form-control-sm fecha-inicio" required></td>
            <td><input type="date" class="form-control form-control-sm fecha-fin" required></td>
            <td><input type="number" class="form-control form-control-sm horas-estimadas" value="${horas}" min="1"></td>
            <td><input type="number" class="form-control form-control-sm cantidad" value="1" min="1" required></td>
            <td>
              <select class="form-select form-select-sm unidad">${unidadesOpts}</select>
            </td>
            <td>
              <select class="form-select form-select-sm asignado">${usuariosOpts}</select>
            </td>
            <td>
              <select class="form-select form-select-sm prioridad">
                <option value="baja">Baja</option>
                <option value="media" selected>Media</option>
                <option value="alta">Alta</option>
              </select>
            </td>
          </tr>
        `;
      }).join('');

      tablaPaso3.innerHTML = rows;
    });
  }

  function validatePaso3() {
    const rows = Array.from(tablaPaso3?.querySelectorAll('tr') || []);
    if (!rows.length) {
      alert('Seleccioná al menos una tarea en el Paso 2.');
      return false;
    }

    const invalid = rows.find((row) => {
      const inicio = row.querySelector('.fecha-inicio')?.value;
      const fin = row.querySelector('.fecha-fin')?.value;
      const cantidad = row.querySelector('.cantidad')?.value;
      return !inicio || !fin || !cantidad;
    });

    if (invalid) {
      alert('Completá las fechas y la cantidad para todas las tareas.');
      return false;
    }
    return true;
  }

  function buildResumen() {
    if (!resumenContainer) {
      return;
    }

    const payload = collectPaso3Payload();
    if (!payload.tareas.length) {
      resumenContainer.innerHTML = '<div class="alert alert-warning">No hay tareas para mostrar en el resumen.</div>';
      return;
    }

    const items = payload.tareas.map((tarea) => `
      <li class="list-group-item">
        <div class="fw-semibold">${tarea.nombre}</div>
        <div class="small text-muted">${tarea.etapa_nombre || tarea.etapa_slug || ''}</div>
        <div class="small">${tarea.fecha_inicio || 'Sin inicio'} → ${tarea.fecha_fin || 'Sin fin'} | ${tarea.cantidad || 1} ${tarea.unidad}</div>
      </li>
    `).join('');

    resumenContainer.innerHTML = `
      <div class="alert alert-info">
        <strong>${payload.tareas.length}</strong> tareas listas para crear.
      </div>
      <ul class="list-group">${items}</ul>
    `;
  }

  function collectPaso3Payload() {
    const rows = Array.from(tablaPaso3?.querySelectorAll('tr') || []);
    const tareas = rows.map((row) => {
      const index = Number(row.getAttribute('data-index')) || 0;
      const task = state.selectedTasks[index] || {};
      const slugRaw = row.getAttribute('data-etapa-slug') || task.etapa_slug || null;
      const idRaw = row.getAttribute('data-etapa-id') || task.catalogo_id;
      const etapaNombreRaw = row.getAttribute('data-etapa-nombre') || task.etapa_nombre || '';
      const meta = resolveEtapaMeta({ slug: slugRaw, catalogId: idRaw, nombre: etapaNombreRaw });
      const etapaSlug = meta.slug || slugRaw || null;
      const etapaCatalogRaw = meta.id || normalizeCatalogId(idRaw);
      const etapaCatalogId = (() => {
        if (etapaCatalogRaw == null) {
          return null;
        }
        const asNumber = Number(etapaCatalogRaw);
        return Number.isFinite(asNumber) ? asNumber : etapaCatalogRaw;
      })();
      const etapaNombre = meta.nombre || etapaNombreRaw;

      const parseNumber = (value) => {
        if (value === '' || value == null) return null;
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
      };

      return {
        nombre: row.querySelector('.tarea-nombre')?.textContent?.trim() || task.nombre || '',
        etapa_slug: etapaSlug,
        catalogo_id: etapaCatalogId,
        etapa_id: etapaCatalogId,
        etapa_nombre: etapaNombre,
        fecha_inicio: row.querySelector('.fecha-inicio')?.value || null,
        fecha_fin: row.querySelector('.fecha-fin')?.value || null,
        horas: parseNumber(row.querySelector('.horas-estimadas')?.value) || null,
        cantidad: parseNumber(row.querySelector('.cantidad')?.value) || null,
        unidad: row.querySelector('.unidad')?.value || task.unidad || 'h',
        asignado_usuario_id: parseNumber(row.querySelector('.asignado')?.value),
        prioridad: row.querySelector('.prioridad')?.value || 'media',
      };
    }).filter((t) => t.nombre && (t.etapa_slug || t.catalogo_id != null));

    return { obra_id: obraId, tareas };
  }

  function showResult(result) {
    if (!resumenContainer) {
      return;
    }

    const ok = result?.ok !== false;
    const creadas = Array.isArray(result?.creadas) ? result.creadas : [];
    const duplicadas = Array.isArray(result?.duplicados) ? result.duplicados : [];

    state.result = ok ? { creadas, duplicadas } : null;
    window.WIZARD = window.WIZARD || {};
    window.WIZARD.resultado = state.result;

    if (!ok) {
      const mensaje = result?.error || 'No se pudieron crear las tareas.';
      resumenContainer.innerHTML = `<div class="alert alert-danger">${mensaje}</div>`;
      if (btnFinish) {
        btnFinish.style.display = 'none';
      }
      if (btnConfirm) {
        btnConfirm.style.display = 'inline-flex';
        btnConfirm.disabled = false;
      }
      return;
    }

    const resumenCreadas = creadas.length
      ? `
        <div class="mb-3">
          <h6 class="fw-semibold">Tareas creadas</h6>
          <ul class="list-group list-group-sm">
            ${creadas.map((t) => `<li class="list-group-item">${t.nombre} <span class="text-muted">(${t.etapa || ''})</span></li>`).join('')}
          </ul>
        </div>
      `
      : '';

    const resumenDuplicadas = duplicadas.length
      ? `
        <div>
          <h6 class="fw-semibold">Tareas duplicadas</h6>
          <ul class="list-group list-group-sm">
            ${duplicadas.map((t) => `<li class="list-group-item">${t.nombre} <span class="text-muted">(${t.etapa || ''})</span></li>`).join('')}
          </ul>
        </div>
      `
      : '';

    resumenContainer.innerHTML = `
      <div class="alert alert-success">
        <strong>${creadas.length}</strong> tareas creadas y <strong>${duplicadas.length}</strong> duplicadas.
      </div>
      ${resumenCreadas}
      ${resumenDuplicadas}
    `;

    if (btnConfirm) {
      btnConfirm.style.display = 'none';
      btnConfirm.disabled = true;
    }
    if (btnFinish) {
      btnFinish.style.display = 'inline-flex';
      btnFinish.disabled = false;
    }

    if (typeof window.refreshEtapasContainer === 'function') {
      window.refreshEtapasContainer();
    }
  }

  function submitPaso4() {
    if (state.submitting) {
      return;
    }

    const payload = collectPaso3Payload();
    if (!payload.tareas.length) {
      alert('No hay tareas para crear.');
      return;
    }

    payload.evitar_duplicados = modal.querySelector('#evitarDuplicados')?.checked ?? true;

    state.submitting = true;
    if (btnConfirm) {
      btnConfirm.disabled = true;
    }

    modal.querySelector('#wizardLoading')?.classList.remove('d-none');

    fetchJSON('/obras/api/wizard-tareas/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then((result) => {
        modal.querySelector('#wizardLoading')?.classList.add('d-none');
        showResult(result);
      })
      .catch((error) => {
        modal.querySelector('#wizardLoading')?.classList.add('d-none');
        resumenContainer.innerHTML = `<div class="alert alert-danger">${error.message}</div>`;
        if (btnConfirm) {
          btnConfirm.style.display = 'inline-flex';
        }
      })
      .finally(() => {
        state.submitting = false;
        if (btnConfirm) {
          btnConfirm.disabled = false;
        }
      });
  }

  function resetWizard() {
    state.step = 1;
    state.selectedEtapas.clear();
    state.selectedTasks = [];
    window.WZ_STATE.etapasSel.clear();
    window.WZ_STATE.tareasSel = [];
    state.result = null;

    if (tablaPaso3) {
      tablaPaso3.innerHTML = '';
    }
    if (resumenContainer) {
      resumenContainer.innerHTML = '';
    }
    if (tareasSeleccionadasPanel) {
      tareasSeleccionadasPanel.innerHTML = '<p class="text-muted">Ninguna tarea seleccionada</p>';
    }
    if (btnConfirm) {
      btnConfirm.style.display = 'none';
      btnConfirm.disabled = false;
    }
    if (btnFinish) {
      btnFinish.style.display = 'none';
      btnFinish.disabled = false;
    }

    loadCatalog().catch((error) => {
      const container = modal.querySelector('#catalogoEtapas');
      if (container) {
        container.innerHTML = `<div class="text-danger">${error.message}</div>`;
      }
    });

    setStep(1);
  }

  function handlePrev() {
    if (state.step === 2) {
      setStep(1);
    } else if (state.step === 3) {
      setStep(2);
    }
  }

  function handleNext() {
    if (state.step === 1) {
      if (state.selectedEtapas.size === 0) {
        alert('Seleccioná al menos una etapa para continuar.');
        return;
      }
      loadTareas()
        .then(() => setStep(2))
        .catch((error) => {
          alert(error.message);
        });
      return;
    }

    if (state.step === 2) {
      if (!state.selectedTasks.length) {
        alert('Seleccioná al menos una tarea.');
        return;
      }
      populatePaso3().then(() => setStep(3));
      return;
    }

    if (state.step === 3) {
      if (!validatePaso3()) {
        return;
      }
      buildResumen();
      setStep(4);
    }
  }

  function handleFinish() {
    const modalInstance = bootstrap.Modal.getInstance(modal);
    if (modalInstance) {
      modalInstance.hide();
    }
    if (typeof window.refreshEtapasContainer === 'function') {
      window.refreshEtapasContainer();
    }
  }

  function handleModalShown() {
    resetWizard();
  }

  function bindEvents() {
    if (btnPrev) {
      btnPrev.addEventListener('click', handlePrev);
    }
    if (btnNext) {
      btnNext.addEventListener('click', handleNext);
    }
    if (btnConfirm) {
      btnConfirm.addEventListener('click', submitPaso4);
    }
    if (btnFinish) {
      btnFinish.addEventListener('click', handleFinish);
    }
    modal.addEventListener('show.bs.modal', handleModalShown);
  }

  function bindCatalogEvents() {
    const container = modal.querySelector('#catalogoEtapas');
    if (!container) {
      return;
    }

    container.querySelectorAll('.etapa-checkbox').forEach((checkbox) => {
      checkbox.addEventListener('change', () => {
        updateEtapasSeleccionadas();
      });
    });
  }

  function seleccionarTodasLasEtapas() {
    modal.querySelectorAll('.etapa-checkbox:not(:disabled)').forEach((checkbox) => {
      checkbox.checked = true;
    });
    updateEtapasSeleccionadas();
    rehydrateChecksFromState();
  }

  function deseleccionarTodasLasEtapas() {
    modal.querySelectorAll('.etapa-checkbox:not(:disabled)').forEach((checkbox) => {
      checkbox.checked = false;
    });
    updateEtapasSeleccionadas();
    rehydrateChecksFromState();
  }

  function updateEtapasBadge() {
    const count = state.selectedEtapas.size;
    const badgeBtn = document.getElementById('btnAgregarEtapasSel');
    if (badgeBtn) {
      badgeBtn.disabled = count === 0;
      badgeBtn.textContent = count > 0 ? `Agregar Etapas Seleccionadas (${count})` : 'Agregar Etapas Seleccionadas';
    }
    if (btnNext && state.step === 1) {
      btnNext.disabled = count === 0;
      btnNext.innerHTML = count > 0
        ? `Siguiente (${count}) <i class="fas fa-arrow-right ms-1"></i>`
        : 'Siguiente <i class="fas fa-arrow-right ms-1"></i>';
    }
  }

  function rehydrateChecksFromState() {
    const keys = new Set(window.WZ_STATE.etapasSel || []);
    modal.querySelectorAll('.etapa-checkbox').forEach((checkbox) => {
      const id = checkbox.dataset.etapaId || '';
      const slug = checkbox.dataset.etapaSlug || '';
      checkbox.checked = keys.has(slug) || keys.has(id);
    });
  }

  function getSelectedEtapaIds() {
    return Array.from(state.selectedEtapas.values())
      .map((meta) => meta.catalogId)
      .filter((id) => id != null);
  }

  // Inicialización
  bindEvents();
  loadCatalog().catch((error) => {
    const container = modal.querySelector('#catalogoEtapas');
    if (container) {
      container.innerHTML = `<div class="text-danger">${error.message}</div>`;
    }
  });
  setStep(1);

  // Exponer helpers globales esperados por HTML legacy
  window.cargarCatalogoEtapas = loadCatalog;
  window.updateEtapasBadge = updateEtapasBadge;
  window.rehydrateChecksFromState = rehydrateChecksFromState;
  window.getSelectedEtapaIds = getSelectedEtapaIds;
  window.updateTaskSelectionPanel = updateTaskSelectionPanel;
  window.populatePaso3 = populatePaso3;
  window.collectPaso3Payload = collectPaso3Payload;
  window.loadTareasWizard = loadTareas;
  window.seleccionarTodasLasEtapas = seleccionarTodasLasEtapas;
  window.deseleccionarTodasLasEtapas = deseleccionarTodasLasEtapas;
  window.bindCatalogEvents = () => bindCatalogEvents();
  window.gotoPaso = setStep;
  window.nextStep = handleNext;
  window.prevStep = handlePrev;

  // Guardar referencias en window para compatibilidad
  window.WIZARD = window.WIZARD || {};
  window.WIZARD.tareas_seleccionadas = state.selectedTasks;

  if (typeof window.withButtonGuard !== 'function') {
    window.withButtonGuard = async (buttonId, fn) => {
      const button = typeof buttonId === 'string' ? document.getElementById(buttonId) : buttonId;
      if (!button) {
        return fn();
      }
      if (button.dataset.guardActive === 'true') {
        return;
      }
      const originalHtml = button.innerHTML;
      const originalDisabled = button.disabled;
      button.dataset.guardActive = 'true';
      button.disabled = true;
      try {
        return await fn();
      } finally {
        button.disabled = originalDisabled;
        button.innerHTML = originalHtml;
        delete button.dataset.guardActive;
      }
    };
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initWizard, { once: true });
} else {
  initWizard();
}
