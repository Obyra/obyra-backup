(() => {
    const TYPE_LABELS = {
        deposito: 'Depósitos',
        obra: 'Obras',
    };

    const groupPriority = (key) => {
        const normalized = (key || '').toLowerCase();
        if (normalized === 'deposito') {
            return 0;
        }
        if (normalized === 'obra') {
            return 1;
        }
        return 2;
    };

    const normaliseType = (value) => {
        const normalized = (value || 'deposito').toString().toLowerCase();
        return normalized === 'obra' ? 'obra' : 'deposito';
    };

    const normaliseOption = (option = {}) => {
        const tipo = normaliseType(option.tipo);
        const nombre = (option.nombre || '').toString().trim();
        const direccion = (option.direccion || '').toString().trim();
        const id = option.id != null ? String(option.id) : '';
        const search = (option.search || `${nombre} ${direccion}`).toString().toLowerCase();
        return {
            id,
            tipo,
            nombre,
            direccion,
            search,
            label: direccion ? `${nombre} – ${direccion}` : nombre,
        };
    };

    const ensureGroups = (groups = []) => {
        const normalized = [];
        groups.forEach((group) => {
            if (!group) {
                return;
            }
            const key = (group.key || group.label || '').toString().toLowerCase() || 'deposito';
            const label = group.label || TYPE_LABELS[key] || key.charAt(0).toUpperCase() + key.slice(1);
            const options = Array.isArray(group.options)
                ? group.options.map(normaliseOption).filter((opt) => opt.id)
                : [];
            normalized.push({
                key,
                label,
                options,
            });
        });

        normalized.sort((a, b) => {
            const priorityDiff = groupPriority(a.key) - groupPriority(b.key);
            if (priorityDiff !== 0) {
                return priorityDiff;
            }
            return a.label.localeCompare(b.label, 'es', { sensitivity: 'base' });
        });

        return normalized;
    };

    const store = {
        groups: [],
        entries: [],
    };

    const rebuildOptionElements = (entry) => {
        const { select } = entry;
        if (!select) {
            return;
        }

        const previous = entry.desiredValue || select.dataset.initialValue || select.value || '';
        const query = (entry.query || '').toLowerCase();

        select.innerHTML = '';
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = 'Seleccionar ubicación...';
        select.appendChild(placeholder);

        let totalOptions = 0;

        store.groups.forEach((group) => {
            const optgroup = document.createElement('optgroup');
            optgroup.label = group.label;
            let visibleCount = 0;

            group.options
                .slice()
                .sort((a, b) => a.nombre.localeCompare(b.nombre, 'es', { sensitivity: 'base' }))
                .forEach((option) => {
                    const optionElement = document.createElement('option');
                    optionElement.value = option.id;
                    optionElement.textContent = option.label || option.nombre;
                    optionElement.dataset.tipo = option.tipo;
                    optionElement.dataset.search = option.search;

                    if (query && !option.search.includes(query)) {
                        optionElement.hidden = true;
                    } else {
                        visibleCount += 1;
                    }

                    optgroup.appendChild(optionElement);
                    totalOptions += 1;
                });

            if (visibleCount === 0) {
                optgroup.hidden = true;
            }

            select.appendChild(optgroup);
        });

        const escapedValue = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(previous) : previous;
        const hasTarget = previous && select.querySelector(`option[value="${escapedValue}"]`);
        const targetValue = hasTarget ? previous : '';
        select.value = targetValue;
        entry.desiredValue = select.value;
        select.disabled = totalOptions === 0;
    };

    const refreshAll = () => {
        store.entries.forEach((entry) => rebuildOptionElements(entry));
    };

    const setGroups = (groups) => {
        store.groups = ensureGroups(groups);
        refreshAll();
    };

    const addLocation = (location) => {
        const option = normaliseOption(location);
        if (!option.id) {
            return;
        }

        let group = store.groups.find((entry) => entry.key === option.tipo);
        if (!group) {
            group = {
                key: option.tipo,
                label: TYPE_LABELS[option.tipo] || option.tipo.charAt(0).toUpperCase() + option.tipo.slice(1),
                options: [],
            };
            store.groups.push(group);
            store.groups.sort((a, b) => groupPriority(a.key) - groupPriority(b.key));
        }

        group.options = group.options.filter((existing) => existing.id !== option.id);
        group.options.push(option);
        refreshAll();

        document.dispatchEvent(new CustomEvent('inventory-location:created', {
            detail: { location: option },
        }));
    };

    const registerSelect = (select, searchInput = null) => {
        if (!select || !(select instanceof HTMLSelectElement)) {
            return null;
        }

        const entry = {
            select,
            searchInput: searchInput instanceof HTMLInputElement ? searchInput : null,
            query: '',
            desiredValue: select.dataset.initialValue || select.value || '',
        };

        store.entries.push(entry);
        rebuildOptionElements(entry);

        if (entry.searchInput) {
            entry.searchInput.addEventListener('input', () => {
                entry.query = (entry.searchInput.value || '').trim().toLowerCase();
                rebuildOptionElements(entry);
            });
        }

        select.addEventListener('change', () => {
            entry.desiredValue = select.value;
        });

        return entry;
    };

    const setValue = (select, value) => {
        if (!select) {
            return;
        }
        const target = store.entries.find((entry) => entry.select === select);
        const desired = value != null ? String(value) : '';
        if (target) {
            target.desiredValue = desired;
            target.select.dataset.initialValue = desired;
            rebuildOptionElements(target);
        } else {
            select.value = desired;
        }
    };

    const getGroups = () => store.groups.map((group) => ({
        key: group.key,
        label: group.label,
        options: group.options.slice(),
    }));

    const modalElement = document.querySelector('[data-location-modal]');
    let bootstrapModal = null;
    if (modalElement && window.bootstrap && typeof window.bootstrap.Modal === 'function') {
        bootstrapModal = new window.bootstrap.Modal(modalElement);
    }

    const modalForm = modalElement ? modalElement.querySelector('[data-location-form]') : null;
    const typeInput = modalElement ? modalElement.querySelector('[data-location-type]') : null;
    const nameInput = modalElement ? modalElement.querySelector('[data-location-name]') : null;
    const addressInput = modalElement ? modalElement.querySelector('[data-location-address]') : null;
    const errorBox = modalElement ? modalElement.querySelector('[data-location-error]') : null;
    const submitButton = modalElement ? modalElement.querySelector('[data-location-submit]') : null;
    const endpoint = modalElement ? modalElement.dataset.locationEndpoint : null;

    let pendingSelects = [];

    const hideError = () => {
        if (errorBox) {
            errorBox.classList.add('d-none');
            errorBox.textContent = '';
        }
    };

    const showError = (message) => {
        if (!errorBox) {
            window.alert(message);
            return;
        }
        errorBox.textContent = message;
        errorBox.classList.remove('d-none');
    };

    const resetModal = () => {
        if (modalForm) {
            modalForm.reset();
        }
        if (typeInput) {
            typeInput.value = 'deposito';
        }
        hideError();
        pendingSelects = [];
    };

    const openModal = (trigger) => {
        if (!modalElement) {
            return;
        }

        resetModal();

        const selectTargets = (trigger?.dataset.selectTarget || '')
            .split(',')
            .map((selector) => selector.trim())
            .filter(Boolean)
            .map((selector) => document.querySelector(selector))
            .filter((element) => element instanceof HTMLSelectElement);
        pendingSelects = selectTargets;

        if (typeInput && trigger?.dataset.locationType) {
            typeInput.value = trigger.dataset.locationType;
        }

        if (bootstrapModal) {
            bootstrapModal.show();
        } else {
            modalElement.classList.add('show');
            modalElement.style.display = 'block';
        }

        if (nameInput) {
            nameInput.focus();
        }
    };

    const closeModal = () => {
        if (!modalElement) {
            return;
        }
        if (bootstrapModal) {
            bootstrapModal.hide();
        } else {
            modalElement.classList.remove('show');
            modalElement.style.display = 'none';
        }
        pendingSelects = [];
    };

    if (modalElement && modalForm && endpoint) {
        modalForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            hideError();

            const nombre = nameInput ? nameInput.value.trim() : '';
            const tipo = typeInput ? typeInput.value : 'deposito';
            const direccion = addressInput ? addressInput.value.trim() : '';

            if (!nombre) {
                showError('Ingresá un nombre para la ubicación.');
                if (nameInput) {
                    nameInput.focus();
                }
                return;
            }

            if (submitButton) {
                submitButton.disabled = true;
            }

            try {
                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        Accept: 'application/json',
                    },
                    body: JSON.stringify({
                        nombre,
                        tipo,
                        direccion,
                    }),
                });

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const payload = await response.json();
                if (!payload || !payload.location) {
                    throw new Error('Respuesta inválida del servidor');
                }

                addLocation(payload.location);

                const locationId = payload.location.id;
                pendingSelects.forEach((select) => setValue(select, locationId));

                closeModal();
                resetModal();
            } catch (error) {
                console.error('[inventario] No se pudo crear la ubicación', error);
                showError('No se pudo crear la ubicación. Intentá nuevamente.');
            } finally {
                if (submitButton) {
                    submitButton.disabled = false;
                }
            }
        });

        modalElement.addEventListener('hidden.bs.modal', () => {
            resetModal();
        });
    }

    document.addEventListener('click', (event) => {
        const trigger = event.target.closest('[data-open-location-modal]');
        if (!trigger) {
            return;
        }
        event.preventDefault();
        openModal(trigger);
    });

    const embeddedGroups = document.querySelector('script[data-location-groups]');
    if (embeddedGroups) {
        try {
            const parsed = JSON.parse(embeddedGroups.textContent || '[]');
            if (Array.isArray(parsed)) {
                setGroups(parsed);
            }
        } catch (error) {
            console.warn('[inventario] No se pudieron parsear las ubicaciones embebidas', error);
        }
    }

    window.inventoryLocations = {
        setGroups,
        addLocation,
        registerSelect,
        setValue,
        getGroups,
    };

    document.dispatchEvent(new CustomEvent('inventory-location:ready'));
})();

