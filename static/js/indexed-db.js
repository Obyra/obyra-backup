/**
 * OBYRA IndexedDB Manager
 * Maneja el almacenamiento local de datos para modo offline
 */

const ObyraDB = {
    DB_NAME: 'obyra-offline',
    DB_VERSION: 1,
    db: null,

    // Stores disponibles
    STORES: {
        OBRAS: 'obras',
        TAREAS: 'tareas',
        AVANCES: 'avances',
        INVENTARIO: 'inventario',
        USUARIOS: 'usuarios',
        SYNC_QUEUE: 'sync_queue',
        FOTOS_PENDIENTES: 'fotos_pendientes',
        CONFIG: 'config'
    },

    /**
     * Inicializar la base de datos
     */
    async init() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.DB_NAME, this.DB_VERSION);

            request.onerror = () => {
                console.error('[IndexedDB] Error abriendo DB:', request.error);
                reject(request.error);
            };

            request.onsuccess = () => {
                this.db = request.result;
                console.log('[IndexedDB] Base de datos abierta correctamente');
                resolve(this.db);
            };

            request.onupgradeneeded = (event) => {
                console.log('[IndexedDB] Actualizando estructura de BD...');
                const db = event.target.result;

                // Store de obras
                if (!db.objectStoreNames.contains(this.STORES.OBRAS)) {
                    const obrasStore = db.createObjectStore(this.STORES.OBRAS, { keyPath: 'id' });
                    obrasStore.createIndex('nombre', 'nombre', { unique: false });
                    obrasStore.createIndex('estado', 'estado', { unique: false });
                    obrasStore.createIndex('updated_at', 'updated_at', { unique: false });
                }

                // Store de tareas
                if (!db.objectStoreNames.contains(this.STORES.TAREAS)) {
                    const tareasStore = db.createObjectStore(this.STORES.TAREAS, { keyPath: 'id' });
                    tareasStore.createIndex('obra_id', 'obra_id', { unique: false });
                    tareasStore.createIndex('estado', 'estado', { unique: false });
                    tareasStore.createIndex('asignado_a', 'asignado_a', { unique: false });
                }

                // Store de avances (pueden ser creados offline)
                if (!db.objectStoreNames.contains(this.STORES.AVANCES)) {
                    const avancesStore = db.createObjectStore(this.STORES.AVANCES, { keyPath: 'id', autoIncrement: true });
                    avancesStore.createIndex('tarea_id', 'tarea_id', { unique: false });
                    avancesStore.createIndex('synced', 'synced', { unique: false });
                    avancesStore.createIndex('created_at', 'created_at', { unique: false });
                }

                // Store de inventario
                if (!db.objectStoreNames.contains(this.STORES.INVENTARIO)) {
                    const invStore = db.createObjectStore(this.STORES.INVENTARIO, { keyPath: 'id' });
                    invStore.createIndex('codigo', 'codigo', { unique: false });
                    invStore.createIndex('categoria_id', 'categoria_id', { unique: false });
                    invStore.createIndex('nombre', 'nombre', { unique: false });
                }

                // Store de usuarios (para cache de asignaciones)
                if (!db.objectStoreNames.contains(this.STORES.USUARIOS)) {
                    const usersStore = db.createObjectStore(this.STORES.USUARIOS, { keyPath: 'id' });
                    usersStore.createIndex('email', 'email', { unique: false });
                }

                // Cola de sincronización
                if (!db.objectStoreNames.contains(this.STORES.SYNC_QUEUE)) {
                    const syncStore = db.createObjectStore(this.STORES.SYNC_QUEUE, { keyPath: 'id', autoIncrement: true });
                    syncStore.createIndex('type', 'type', { unique: false });
                    syncStore.createIndex('created_at', 'created_at', { unique: false });
                }

                // Fotos pendientes de subir
                if (!db.objectStoreNames.contains(this.STORES.FOTOS_PENDIENTES)) {
                    const fotosStore = db.createObjectStore(this.STORES.FOTOS_PENDIENTES, { keyPath: 'id', autoIncrement: true });
                    fotosStore.createIndex('avance_id', 'avance_id', { unique: false });
                    fotosStore.createIndex('synced', 'synced', { unique: false });
                }

                // Configuración local
                if (!db.objectStoreNames.contains(this.STORES.CONFIG)) {
                    db.createObjectStore(this.STORES.CONFIG, { keyPath: 'key' });
                }
            };
        });
    },

    /**
     * Obtener un registro por ID
     */
    async get(storeName, id) {
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(storeName, 'readonly');
            const store = tx.objectStore(storeName);
            const request = store.get(id);

            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    },

    /**
     * Obtener todos los registros de un store
     */
    async getAll(storeName) {
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(storeName, 'readonly');
            const store = tx.objectStore(storeName);
            const request = store.getAll();

            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    },

    /**
     * Obtener registros por índice
     */
    async getByIndex(storeName, indexName, value) {
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(storeName, 'readonly');
            const store = tx.objectStore(storeName);
            const index = store.index(indexName);
            const request = index.getAll(value);

            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    },

    /**
     * Guardar un registro (insert o update)
     */
    async put(storeName, data) {
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(storeName, 'readwrite');
            const store = tx.objectStore(storeName);
            const request = store.put(data);

            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    },

    /**
     * Guardar múltiples registros
     */
    async putMany(storeName, items) {
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(storeName, 'readwrite');
            const store = tx.objectStore(storeName);

            items.forEach(item => store.put(item));

            tx.oncomplete = () => resolve(items.length);
            tx.onerror = () => reject(tx.error);
        });
    },

    /**
     * Eliminar un registro
     */
    async delete(storeName, id) {
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(storeName, 'readwrite');
            const store = tx.objectStore(storeName);
            const request = store.delete(id);

            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });
    },

    /**
     * Limpiar un store completo
     */
    async clear(storeName) {
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(storeName, 'readwrite');
            const store = tx.objectStore(storeName);
            const request = store.clear();

            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });
    },

    /**
     * Contar registros en un store
     */
    async count(storeName) {
        return new Promise((resolve, reject) => {
            const tx = this.db.transaction(storeName, 'readonly');
            const store = tx.objectStore(storeName);
            const request = store.count();

            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    },

    // ========================================================================
    // MÉTODOS ESPECÍFICOS PARA OBYRA
    // ========================================================================

    /**
     * Guardar obras del usuario
     */
    async saveObras(obras) {
        await this.putMany(this.STORES.OBRAS, obras);
        await this.setConfig('last_sync_obras', Date.now());
        console.log(`[IndexedDB] ${obras.length} obras guardadas`);
    },

    /**
     * Obtener obras locales
     */
    async getObras() {
        return this.getAll(this.STORES.OBRAS);
    },

    /**
     * Guardar tareas de una obra
     */
    async saveTareas(tareas) {
        await this.putMany(this.STORES.TAREAS, tareas);
        console.log(`[IndexedDB] ${tareas.length} tareas guardadas`);
    },

    /**
     * Obtener tareas de una obra
     */
    async getTareasByObra(obraId) {
        return this.getByIndex(this.STORES.TAREAS, 'obra_id', obraId);
    },

    /**
     * Obtener tareas asignadas al usuario actual
     */
    async getMisTareas(userId) {
        return this.getByIndex(this.STORES.TAREAS, 'asignado_a', userId);
    },

    /**
     * Crear un avance offline
     */
    async createAvanceOffline(avanceData) {
        const avance = {
            ...avanceData,
            synced: false,
            created_at: new Date().toISOString(),
            offline_id: `offline_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
        };

        const id = await this.put(this.STORES.AVANCES, avance);

        // Agregar a cola de sincronización
        await this.addToSyncQueue({
            type: 'CREATE_AVANCE',
            data: avance,
            created_at: Date.now()
        });

        console.log('[IndexedDB] Avance creado offline:', id);
        return { ...avance, id };
    },

    /**
     * Obtener avances pendientes de sincronizar
     */
    async getAvancesPendientes() {
        return this.getByIndex(this.STORES.AVANCES, 'synced', false);
    },

    /**
     * Marcar avance como sincronizado
     */
    async markAvanceSynced(localId, serverId) {
        const avance = await this.get(this.STORES.AVANCES, localId);
        if (avance) {
            avance.synced = true;
            avance.server_id = serverId;
            await this.put(this.STORES.AVANCES, avance);
        }
    },

    /**
     * Guardar foto para subir después
     */
    async saveFotoPendiente(fotoData) {
        const foto = {
            ...fotoData,
            synced: false,
            created_at: Date.now()
        };
        return this.put(this.STORES.FOTOS_PENDIENTES, foto);
    },

    /**
     * Obtener fotos pendientes de subir
     */
    async getFotosPendientes() {
        return this.getByIndex(this.STORES.FOTOS_PENDIENTES, 'synced', false);
    },

    /**
     * Guardar inventario local
     */
    async saveInventario(items) {
        await this.putMany(this.STORES.INVENTARIO, items);
        await this.setConfig('last_sync_inventario', Date.now());
        console.log(`[IndexedDB] ${items.length} items de inventario guardados`);
    },

    /**
     * Buscar en inventario local
     */
    async searchInventario(query) {
        const items = await this.getAll(this.STORES.INVENTARIO);
        const queryLower = query.toLowerCase();
        return items.filter(item =>
            item.nombre.toLowerCase().includes(queryLower) ||
            item.codigo.toLowerCase().includes(queryLower)
        );
    },

    /**
     * Agregar operación a cola de sincronización
     */
    async addToSyncQueue(operation) {
        return this.put(this.STORES.SYNC_QUEUE, operation);
    },

    /**
     * Obtener cola de sincronización
     */
    async getSyncQueue() {
        return this.getAll(this.STORES.SYNC_QUEUE);
    },

    /**
     * Limpiar operación de la cola
     */
    async removeFromSyncQueue(id) {
        return this.delete(this.STORES.SYNC_QUEUE, id);
    },

    /**
     * Guardar configuración
     */
    async setConfig(key, value) {
        return this.put(this.STORES.CONFIG, { key, value });
    },

    /**
     * Obtener configuración
     */
    async getConfig(key) {
        const config = await this.get(this.STORES.CONFIG, key);
        return config ? config.value : null;
    },

    /**
     * Obtener estadísticas de almacenamiento local
     */
    async getStats() {
        const stats = {
            obras: await this.count(this.STORES.OBRAS),
            tareas: await this.count(this.STORES.TAREAS),
            avances: await this.count(this.STORES.AVANCES),
            inventario: await this.count(this.STORES.INVENTARIO),
            pendientes_sync: await this.count(this.STORES.SYNC_QUEUE),
            fotos_pendientes: await this.count(this.STORES.FOTOS_PENDIENTES),
            last_sync_obras: await this.getConfig('last_sync_obras'),
            last_sync_inventario: await this.getConfig('last_sync_inventario')
        };
        return stats;
    }
};

// Auto-inicializar cuando se carga el script
if (typeof window !== 'undefined') {
    window.ObyraDB = ObyraDB;
}
