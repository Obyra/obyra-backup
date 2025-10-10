(() => {
    const contextElement = document.getElementById('inventory-items-context');
    let context = {
        warehouses: [],
        base_items_url: '',
        can_manage_movements: false,
        has_warehouses: false,
    };

    if (contextElement) {
        try {
            const parsed = JSON.parse(contextElement.textContent || '{}');
            if (parsed && typeof parsed === 'object') {
                context = Object.assign(context, parsed);
            }
        } catch (error) {
            console.warn('[inventario] No se pudo parsear el contexto de items', error);
        }
    }

    const table = document.querySelector('[data-items-table]');
    if (table) {
        const highlightId = table.dataset.highlightId;
        if (highlightId) {
            const targetRow = table.querySelector(`[data-item-id="${highlightId}"]`);
            if (targetRow) {
                targetRow.classList.add('table-success');
                targetRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
                setTimeout(() => {
                    targetRow.classList.remove('table-success');
                }, 2000);
            }
        }
    }

    const modalElement = document.getElementById('inventoryMovementModal');
    if (!modalElement) {
        return;
    }

    const bootstrapModal = window.bootstrap ? new window.bootstrap.Modal(modalElement) : null;
    const form = modalElement.querySelector('[data-movement-form]');
    if (!form) {
        return;
    }

    const measurementSelect = modalElement.querySelector('[data-field="measurement-select"]');
    const measurementHint = modalElement.querySelector('[data-field="measurement-hint"]');
    const measurementModeInput = modalElement.querySelector('[data-field="measurement-mode"]');
    const presentationKeyInput = modalElement.querySelector('[data-field="presentation-key"]');
    const presentationQtyInput = modalElement.querySelector('[data-field="presentation-qty"]');
    const qtyInput = modalElement.querySelector('[data-field="qty"]');
    const nuevoStockInput = modalElement.querySelector('[data-field="nuevo-stock"]');
    const nextInput = modalElement.querySelector('[data-field="next-url"]');
    const quantityInput = modalElement.querySelector('[data-field="quantity-input"]');
    const quantityLabel = modalElement.querySelector('[data-field="quantity-label"]');
    const conversionHint = modalElement.querySelector('[data-field="conversion-hint"]');
    const itemNameLabel = modalElement.querySelector('[data-field="item-name"]');
    const itemSkuLabel = modalElement.querySelector('[data-field="item-sku"]');
    const originWrapper = modalElement.querySelector('[data-field="origin-wrapper"]');
    const destinationWrapper = modalElement.querySelector('[data-field="destination-wrapper"]');
    const originSelect = modalElement.querySelector('[data-field="origin-select"]');
    const destinationSelect = modalElement.querySelector('[data-field="destination-select"]');
    const submitButton = modalElement.querySelector('[data-field="submit-button"]');
    const motiveInput = modalElement.querySelector('[data-field="motive-input"]');
    const formTitle = modalElement.querySelector('[data-movement-title]');

    let currentItem = null;
    let currentAction = null;
    let packagesMap = {};

    const ACTION_CONFIG = {
        ingreso: {
            title: 'Registrar ingreso de stock',
            submitText: 'Registrar ingreso',
            quantityLabel: 'Cantidad a ingresar',
            motivePlaceholder: 'Ej: compra de materiales',
            showOrigin: false,
            showDestination: true,
        },
        egreso: {
            title: 'Registrar egreso de stock',
            submitText: 'Registrar egreso',
            quantityLabel: 'Cantidad a egresar',
            motivePlaceholder: 'Ej: consumo en obra',
            showOrigin: true,
            showDestination: false,
        },
        transferencia: {
            title: 'Transferir entre depósitos',
            submitText: 'Registrar transferencia',
            quantityLabel: 'Cantidad a transferir',
            motivePlaceholder: 'Ej: traslado entre depósitos',
            showOrigin: true,
            showDestination: true,
        },
        ajuste: {
            title: 'Ajustar stock',
            submitText: 'Guardar ajuste',
            quantityLabel: 'Nuevo stock objetivo',
            motivePlaceholder: 'Ej: inventario físico',
            showOrigin: false,
            showDestination: true,
        },
    };

    const buildMeasurementOption = (value, label) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        return option;
    };

    const clearSelect = (select) => {
        if (!select) {
            return;
        }
        while (select.firstChild) {
            select.removeChild(select.firstChild);
        }
    };

    const appendHighlightToUrl = (baseUrl, itemId) => {
        if (!baseUrl) {
            return '';
        }
        try {
            const url = new URL(baseUrl, window.location.origin);
            url.searchParams.set('highlight', itemId);
            return url.pathname + url.search + url.hash;
        } catch (error) {
            // baseUrl could be a relative path without leading slash
            try {
                const normalized = baseUrl.startsWith('/') ? baseUrl : `/${baseUrl}`;
                const url = new URL(normalized, window.location.origin);
                url.searchParams.set('highlight', itemId);
                return url.pathname + url.search + url.hash;
            } catch (err) {
                console.warn('[inventario] No se pudo preparar el redirect con highlight', err);
                return baseUrl;
            }
        }
    };

    const updateMeasurementUI = () => {
        if (!measurementSelect || !currentItem) {
            return;
        }
        const selectedValue = measurementSelect.value;
        const isBase = selectedValue === '__base__' || !selectedValue;
        measurementModeInput.value = isBase ? 'base' : 'package';

        if (isBase) {
            presentationKeyInput.value = '';
            conversionHint.hidden = true;
            conversionHint.textContent = '';
            measurementHint.textContent = `Registrá la cantidad en ${currentItem.unidad || 'la unidad base'}.`;
        } else {
            const pkg = packagesMap[selectedValue];
            if (pkg) {
                presentationKeyInput.value = pkg.key;
                conversionHint.hidden = false;
                conversionHint.textContent = `Se convertirá automáticamente a ${currentItem.unidad || 'la unidad base'} (1 ${pkg.unit || 'unidad'} = ${pkg.multiplier} ${currentItem.unidad || ''}).`;
                measurementHint.textContent = `Ingresá la cantidad en ${pkg.unit || 'presentaciones'} (${pkg.label || ''}).`;
            } else {
                presentationKeyInput.value = '';
                conversionHint.hidden = true;
                conversionHint.textContent = '';
                measurementHint.textContent = '';
            }
        }

        if (currentAction === 'ajuste') {
            quantityLabel.textContent = 'Nuevo stock objetivo';
        } else {
            const config = ACTION_CONFIG[currentAction] || ACTION_CONFIG.ingreso;
            quantityLabel.textContent = config.quantityLabel;
        }
    };

    const resetFormFields = () => {
        if (!form) {
            return;
        }
        form.reset();
        if (originSelect) {
            originSelect.value = '';
            originSelect.disabled = false;
        }
        if (destinationSelect) {
            destinationSelect.value = '';
            destinationSelect.disabled = false;
        }
        if (quantityInput) {
            quantityInput.value = '';
            quantityInput.disabled = false;
        }
        if (motiveInput) {
            motiveInput.value = '';
            motiveInput.disabled = false;
        }
        packagesMap = {};
        if (measurementSelect) {
            clearSelect(measurementSelect);
            measurementSelect.disabled = false;
        }
        conversionHint.hidden = true;
        conversionHint.textContent = '';
        presentationKeyInput.value = '';
        presentationQtyInput.value = '';
        qtyInput.value = '';
        nuevoStockInput.value = '';
    };

    const configureWarehousesVisibility = (config) => {
        if (originWrapper) {
            originWrapper.toggleAttribute('hidden', !config.showOrigin);
        }
        if (destinationWrapper) {
            destinationWrapper.toggleAttribute('hidden', !config.showDestination);
        }
        if (originSelect) {
            originSelect.required = !!config.showOrigin;
        }
        if (destinationSelect) {
            destinationSelect.required = !!config.showDestination;
        }
    };

    const configureMeasurementOptions = (item) => {
        if (!measurementSelect) {
            return;
        }
        clearSelect(measurementSelect);
        const baseLabel = item.unidad ? `Unidad base (${item.unidad})` : 'Unidad base';
        measurementSelect.appendChild(buildMeasurementOption('__base__', baseLabel));
        packagesMap = {};

        if (Array.isArray(item.package_options)) {
            item.package_options.forEach((pkg) => {
                if (!pkg || !pkg.key) {
                    return;
                }
                packagesMap[pkg.key] = pkg;
                const labelParts = [pkg.label || pkg.unit || 'Presentación'];
                if (pkg.multiplier) {
                    labelParts.push(`(${pkg.multiplier} ${item.unidad || 'unidad base'})`);
                }
                measurementSelect.appendChild(buildMeasurementOption(pkg.key, labelParts.join(' ')));
            });
        }

        measurementSelect.disabled = measurementSelect.options.length <= 1;
        measurementSelect.value = '__base__';
        updateMeasurementUI();
    };

    const openMovementModal = (item, action) => {
        if (!item || !action) {
            return;
        }
        currentItem = item;
        currentAction = action;
        resetFormFields();

        const config = ACTION_CONFIG[action] || ACTION_CONFIG.ingreso;
        if (formTitle) {
            formTitle.textContent = config.title;
        }
        if (submitButton) {
            submitButton.textContent = config.submitText;
            submitButton.disabled = !context.can_manage_movements || !context.has_warehouses;
        }
        if (motiveInput) {
            motiveInput.placeholder = config.motivePlaceholder;
        }
        if (itemNameLabel) {
            itemNameLabel.textContent = item.nombre || 'Item de inventario';
        }
        if (itemSkuLabel) {
            itemSkuLabel.textContent = item.sku ? `SKU: ${item.sku}` : '';
        }

        configureWarehousesVisibility(config);
        configureMeasurementOptions(item);
        updateMeasurementUI();

        if (bootstrapModal) {
            bootstrapModal.show();
        } else {
            modalElement.classList.add('show');
            modalElement.style.display = 'block';
        }

        if (!context.has_warehouses) {
            if (originSelect) {
                originSelect.disabled = true;
            }
            if (destinationSelect) {
                destinationSelect.disabled = true;
            }
            if (measurementSelect) {
                measurementSelect.disabled = true;
            }
            if (quantityInput) {
                quantityInput.disabled = true;
            }
            if (motiveInput) {
                motiveInput.disabled = true;
            }
        }
        if (!context.can_manage_movements && submitButton) {
            submitButton.disabled = true;
        }
    };

    if (measurementSelect) {
        measurementSelect.addEventListener('change', () => {
            updateMeasurementUI();
        });
    }

    if (form) {
        form.addEventListener('submit', (event) => {
            if (!context.can_manage_movements || !context.has_warehouses) {
                event.preventDefault();
                return;
            }

            const measurementValue = measurementSelect ? measurementSelect.value : '__base__';
            const quantityValue = quantityInput ? quantityInput.value.trim() : '';

            if (currentAction === 'ajuste') {
                qtyInput.value = '';
                nuevoStockInput.value = quantityValue;
            } else {
                nuevoStockInput.value = '';
                qtyInput.value = measurementValue === '__base__' ? quantityValue : '';
            }

            if (measurementValue !== '__base__') {
                presentationQtyInput.value = quantityValue;
            } else {
                presentationQtyInput.value = '';
                presentationKeyInput.value = '';
            }

            if (nextInput && currentItem) {
                nextInput.value = appendHighlightToUrl(context.base_items_url, currentItem.id);
            }
        });
    }

    const movementButtons = document.querySelectorAll('[data-movement-action][data-item-trigger]');
    movementButtons.forEach((button) => {
        button.addEventListener('click', () => {
            const itemId = button.dataset.itemTrigger;
            const action = button.dataset.movementAction;
            if (!itemId || !action) {
                return;
            }
            const row = table ? table.querySelector(`[data-item-id="${itemId}"]`) : null;
            if (!row) {
                return;
            }
            try {
                const payload = JSON.parse(row.dataset.item || '{}');
                openMovementModal(payload, action);
            } catch (error) {
                console.warn('[inventario] No se pudo parsear el item seleccionado', error);
            }
        });
    });
})();

