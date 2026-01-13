/**
 * OBYRA Offline Manager
 * Coordina el modo offline, sincronización y notificaciones
 */

const OfflineManager = {
    isOnline: navigator.onLine,
    syncInProgress: false,
    serviceWorkerReady: false,

    /**
     * Inicializar el manager offline
     */
    async init() {
        console.log('[Offline] Inicializando modo offline...');

        // Inicializar IndexedDB
        try {
            await ObyraDB.init();
            console.log('[Offline] IndexedDB inicializado');
        } catch (error) {
            console.error('[Offline] Error inicializando IndexedDB:', error);
        }

        // Registrar Service Worker
        await this.registerServiceWorker();

        // Configurar listeners de conexión
        this.setupConnectionListeners();

        // Configurar listener de mensajes del SW
        this.setupServiceWorkerMessages();

        // Mostrar estado inicial
        this.updateConnectionUI();

        // Si estamos online, sincronizar datos iniciales
        if (this.isOnline) {
            this.downloadInitialData();
        }

        console.log('[Offline] Manager inicializado. Online:', this.isOnline);
    },

    /**
     * Registrar Service Worker
     */
    async registerServiceWorker() {
        if ('serviceWorker' in navigator) {
            try {
                const registration = await navigator.serviceWorker.register('/sw.js', {
                    scope: '/'
                });

                console.log('[Offline] Service Worker registrado:', registration.scope);

                registration.addEventListener('updatefound', () => {
                    const newWorker = registration.installing;
                    newWorker.addEventListener('statechange', () => {
                        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                            this.showUpdateNotification();
                        }
                    });
                });

                this.serviceWorkerReady = true;
            } catch (error) {
                console.error('[Offline] Error registrando Service Worker:', error);
            }
        } else {
            console.warn('[Offline] Service Workers no soportados');
        }
    },

    /**
     * Configurar listeners de conexión
     */
    setupConnectionListeners() {
        window.addEventListener('online', () => {
            console.log('[Offline] Conexión restaurada');
            this.isOnline = true;
            this.updateConnectionUI();
            this.showNotification('Conexión restaurada', 'Sincronizando cambios...', 'success');
            this.syncPendingChanges();
        });

        window.addEventListener('offline', () => {
            console.log('[Offline] Conexión perdida');
            this.isOnline = false;
            this.updateConnectionUI();
            this.showNotification('Sin conexión', 'Los cambios se guardarán localmente', 'warning');
        });
    },

    /**
     * Configurar mensajes del Service Worker
     */
    setupServiceWorkerMessages() {
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.addEventListener('message', (event) => {
                const { type, url, method } = event.data;

                switch (type) {
                    case 'DATA_UPDATED':
                        console.log('[Offline] Datos actualizados:', url);
                        break;

                    case 'QUEUED_FOR_SYNC':
                        this.showNotification('Guardado offline', `${method} será sincronizado cuando haya conexión`, 'info');
                        this.updatePendingBadge();
                        break;

                    case 'SYNC_SUCCESS':
                        console.log('[Offline] Sincronización exitosa:', url);
                        this.updatePendingBadge();
                        break;
                }
            });
        }
    },

    /**
     * Actualizar UI según estado de conexión
     */
    updateConnectionUI() {
        // Agregar o quitar clase al body
        document.body.classList.toggle('offline-mode', !this.isOnline);

        // Actualizar indicador de conexión si existe
        const indicator = document.getElementById('connection-indicator');
        if (indicator) {
            indicator.innerHTML = this.isOnline
                ? '<i class="fas fa-wifi text-success"></i>'
                : '<i class="fas fa-wifi-slash text-warning"></i>';
            indicator.title = this.isOnline ? 'Conectado' : 'Sin conexión - Modo offline';
        }

        // Mostrar/ocultar banner offline
        this.toggleOfflineBanner(!this.isOnline);
    },

    /**
     * Mostrar/ocultar banner de modo offline
     */
    toggleOfflineBanner(show) {
        let banner = document.getElementById('offline-banner');

        if (show && !banner) {
            banner = document.createElement('div');
            banner.id = 'offline-banner';
            banner.className = 'offline-banner';
            banner.innerHTML = `
                <div class="offline-banner-content">
                    <i class="fas fa-cloud-slash me-2"></i>
                    <span>Modo offline - Los cambios se sincronizarán automáticamente</span>
                    <span class="pending-count ms-2" id="pending-sync-count"></span>
                </div>
            `;
            document.body.insertBefore(banner, document.body.firstChild);
        } else if (!show && banner) {
            banner.remove();
        }

        if (show) {
            this.updatePendingBadge();
        }
    },

    /**
     * Actualizar contador de pendientes
     */
    async updatePendingBadge() {
        const countEl = document.getElementById('pending-sync-count');
        if (countEl) {
            const queue = await ObyraDB.getSyncQueue();
            const count = queue.length;
            countEl.textContent = count > 0 ? `(${count} pendientes)` : '';
        }
    },

    /**
     * Descargar datos iniciales para offline
     */
    async downloadInitialData() {
        if (!this.isOnline) return;

        console.log('[Offline] Descargando datos para modo offline...');

        try {
            // Descargar obras del usuario
            const obrasResponse = await fetch('/api/offline/mis-obras');
            if (obrasResponse.ok) {
                const obrasData = await obrasResponse.json();
                if (obrasData.obras) {
                    await ObyraDB.saveObras(obrasData.obras);
                }
            }

            // Descargar tareas asignadas
            const tareasResponse = await fetch('/api/offline/mis-tareas');
            if (tareasResponse.ok) {
                const tareasData = await tareasResponse.json();
                if (tareasData.tareas) {
                    await ObyraDB.saveTareas(tareasData.tareas);
                }
            }

            // Descargar inventario básico (solo nombres y códigos para búsqueda)
            const invResponse = await fetch('/api/offline/inventario-basico?limit=1000');
            if (invResponse.ok) {
                const invData = await invResponse.json();
                if (invData.items) {
                    await ObyraDB.saveInventario(invData.items);
                }
            }

            const stats = await ObyraDB.getStats();
            console.log('[Offline] Datos descargados:', stats);

        } catch (error) {
            console.error('[Offline] Error descargando datos:', error);
        }
    },

    /**
     * Sincronizar cambios pendientes
     */
    async syncPendingChanges() {
        if (!this.isOnline || this.syncInProgress) return;

        this.syncInProgress = true;
        console.log('[Offline] Sincronizando cambios pendientes...');

        try {
            const queue = await ObyraDB.getSyncQueue();

            for (const operation of queue) {
                try {
                    let response;

                    switch (operation.type) {
                        case 'CREATE_AVANCE':
                            response = await this.syncAvance(operation.data);
                            break;

                        case 'UPDATE_TAREA':
                            response = await this.syncTarea(operation.data);
                            break;

                        case 'UPLOAD_FOTO':
                            response = await this.syncFoto(operation.data);
                            break;

                        default:
                            console.warn('[Offline] Tipo de operación desconocido:', operation.type);
                    }

                    if (response && response.ok) {
                        await ObyraDB.removeFromSyncQueue(operation.id);
                        console.log('[Offline] Operación sincronizada:', operation.type);
                    }

                } catch (error) {
                    console.error('[Offline] Error sincronizando operación:', error);
                }
            }

            // Actualizar contador
            this.updatePendingBadge();

            // Descargar datos frescos
            await this.downloadInitialData();

        } finally {
            this.syncInProgress = false;
        }
    },

    /**
     * Sincronizar un avance
     */
    async syncAvance(avanceData) {
        const response = await fetch('/api/offline/crear-avance', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(avanceData)
        });

        if (response.ok) {
            const result = await response.json();
            // Marcar como sincronizado en IndexedDB
            if (avanceData.id) {
                await ObyraDB.markAvanceSynced(avanceData.id, result.avance_id);
            }
        }

        return response;
    },

    /**
     * Sincronizar actualización de tarea
     */
    async syncTarea(tareaData) {
        return fetch(`/api/offline/actualizar-tarea/${tareaData.id}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(tareaData)
        });
    },

    /**
     * Sincronizar foto
     */
    async syncFoto(fotoData) {
        const formData = new FormData();
        formData.append('avance_id', fotoData.avance_id);
        formData.append('foto', fotoData.blob, fotoData.filename);

        return fetch('/api/avances/upload-foto', {
            method: 'POST',
            body: formData
        });
    },

    /**
     * Crear avance (funciona online y offline)
     */
    async crearAvance(avanceData) {
        if (this.isOnline) {
            try {
                const response = await fetch('/api/offline/crear-avance', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(avanceData)
                });

                if (response.ok) {
                    return response.json();
                }
            } catch (error) {
                console.log('[Offline] Fallback a modo offline para crear avance');
            }
        }

        // Guardar offline
        const avance = await ObyraDB.createAvanceOffline(avanceData);
        this.showNotification('Guardado offline', 'El avance se sincronizará cuando haya conexión', 'info');
        return { ok: true, offline: true, avance };
    },

    /**
     * Guardar foto para subir después
     */
    async guardarFotoOffline(avanceId, file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();

            reader.onload = async (e) => {
                const fotoData = {
                    avance_id: avanceId,
                    blob: e.target.result,
                    filename: file.name,
                    type: file.type,
                    size: file.size
                };

                await ObyraDB.saveFotoPendiente(fotoData);
                await ObyraDB.addToSyncQueue({
                    type: 'UPLOAD_FOTO',
                    data: fotoData,
                    created_at: Date.now()
                });

                resolve(fotoData);
            };

            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    },

    /**
     * Mostrar notificación
     */
    showNotification(title, message, type = 'info') {
        // Usar toast de Bootstrap si está disponible
        if (typeof bootstrap !== 'undefined') {
            const toastContainer = document.getElementById('toast-container') || this.createToastContainer();

            const toastEl = document.createElement('div');
            toastEl.className = `toast align-items-center text-white bg-${type === 'success' ? 'success' : type === 'warning' ? 'warning' : type === 'error' ? 'danger' : 'info'}`;
            toastEl.setAttribute('role', 'alert');
            toastEl.innerHTML = `
                <div class="d-flex">
                    <div class="toast-body">
                        <strong>${title}</strong><br>
                        ${message}
                    </div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
                </div>
            `;

            toastContainer.appendChild(toastEl);
            const toast = new bootstrap.Toast(toastEl);
            toast.show();

            toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
        } else {
            // Fallback a alert
            console.log(`[${type.toUpperCase()}] ${title}: ${message}`);
        }
    },

    /**
     * Crear contenedor de toasts si no existe
     */
    createToastContainer() {
        const container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        container.style.zIndex = '9999';
        document.body.appendChild(container);
        return container;
    },

    /**
     * Mostrar notificación de actualización disponible
     */
    showUpdateNotification() {
        const banner = document.createElement('div');
        banner.className = 'update-banner';
        banner.innerHTML = `
            <div class="update-banner-content">
                <span>Nueva versión disponible</span>
                <button class="btn btn-sm btn-light ms-3" onclick="location.reload()">
                    Actualizar
                </button>
            </div>
        `;
        document.body.insertBefore(banner, document.body.firstChild);
    },

    /**
     * Obtener estadísticas de datos offline
     */
    async getOfflineStats() {
        return ObyraDB.getStats();
    },

    /**
     * Forzar sincronización manual
     */
    async forceSync() {
        if (!this.isOnline) {
            this.showNotification('Sin conexión', 'No se puede sincronizar sin internet', 'warning');
            return;
        }

        this.showNotification('Sincronizando', 'Sincronizando datos...', 'info');
        await this.syncPendingChanges();
        this.showNotification('Listo', 'Sincronización completada', 'success');
    },

    /**
     * Limpiar todos los datos offline
     */
    async clearOfflineData() {
        if (confirm('¿Eliminar todos los datos offline? Los cambios no sincronizados se perderán.')) {
            await ObyraDB.clear(ObyraDB.STORES.OBRAS);
            await ObyraDB.clear(ObyraDB.STORES.TAREAS);
            await ObyraDB.clear(ObyraDB.STORES.INVENTARIO);
            await ObyraDB.clear(ObyraDB.STORES.SYNC_QUEUE);
            this.showNotification('Datos eliminados', 'Se han eliminado los datos offline', 'info');
        }
    }
};

// CSS para el modo offline
const offlineStyles = `
    .offline-mode {
        --offline-banner-height: 36px;
    }

    .offline-banner {
        background: linear-gradient(90deg, #f59e0b, #d97706);
        color: white;
        padding: 8px 16px;
        text-align: center;
        font-size: 14px;
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        z-index: 10000;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    }

    .offline-banner-content {
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .offline-mode .navbar {
        margin-top: var(--offline-banner-height);
    }

    .update-banner {
        background: linear-gradient(90deg, #10b981, #059669);
        color: white;
        padding: 8px 16px;
        text-align: center;
        font-size: 14px;
    }

    .pending-count {
        background: rgba(255,255,255,0.2);
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 12px;
    }

    #connection-indicator {
        cursor: help;
    }
`;

// Inyectar estilos
if (typeof document !== 'undefined') {
    const styleSheet = document.createElement('style');
    styleSheet.textContent = offlineStyles;
    document.head.appendChild(styleSheet);
}

// Auto-inicializar cuando el DOM esté listo
if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => OfflineManager.init());
    } else {
        OfflineManager.init();
    }
}

// Exportar para uso global
if (typeof window !== 'undefined') {
    window.OfflineManager = OfflineManager;
}
