/**
 * OBYRA Service Worker - Modo Offline
 * Permite a los operarios trabajar sin conexión a internet
 */

const CACHE_VERSION = 'v1.0.0';
const STATIC_CACHE = `obyra-static-${CACHE_VERSION}`;
const DYNAMIC_CACHE = `obyra-dynamic-${CACHE_VERSION}`;
const DATA_CACHE = `obyra-data-${CACHE_VERSION}`;

// Archivos estáticos que siempre se cachean
const STATIC_ASSETS = [
    '/',
    '/static/css/style.css',
    '/static/css/bootstrap.min.css',
    '/static/js/app.js',
    '/static/js/offline-manager.js',
    '/static/js/indexed-db.js',
    '/static/img/logo.png',
    '/offline',
    // Bootstrap y dependencias CDN
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css'
];

// Rutas que se pueden usar offline (solo GET)
const OFFLINE_ROUTES = [
    '/obras/',
    '/obras/mis-tareas',
    '/inventario/',
    '/presupuestos/'
];

// Rutas de API para sincronización
const API_ROUTES = [
    '/api/obras/',
    '/api/tareas/',
    '/api/avances/',
    '/api/inventario/'
];

// ============================================================================
// INSTALACIÓN
// ============================================================================
self.addEventListener('install', (event) => {
    console.log('[SW] Instalando Service Worker...');

    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then((cache) => {
                console.log('[SW] Cacheando archivos estáticos...');
                // Cachear uno por uno para manejar errores
                return Promise.allSettled(
                    STATIC_ASSETS.map(url =>
                        cache.add(url).catch(err => {
                            console.warn(`[SW] No se pudo cachear: ${url}`, err);
                        })
                    )
                );
            })
            .then(() => {
                console.log('[SW] Instalación completada');
                return self.skipWaiting();
            })
    );
});

// ============================================================================
// ACTIVACIÓN
// ============================================================================
self.addEventListener('activate', (event) => {
    console.log('[SW] Activando Service Worker...');

    event.waitUntil(
        caches.keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames
                        .filter(name => {
                            // Eliminar caches viejos
                            return name.startsWith('obyra-') &&
                                   name !== STATIC_CACHE &&
                                   name !== DYNAMIC_CACHE &&
                                   name !== DATA_CACHE;
                        })
                        .map(name => {
                            console.log(`[SW] Eliminando cache viejo: ${name}`);
                            return caches.delete(name);
                        })
                );
            })
            .then(() => {
                console.log('[SW] Activación completada');
                return self.clients.claim();
            })
    );
});

// ============================================================================
// FETCH - Interceptar peticiones
// ============================================================================
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Solo manejar GET requests
    if (event.request.method !== 'GET') {
        // Para POST/PUT/DELETE, intentar online o guardar en cola
        if (event.request.method === 'POST' || event.request.method === 'PUT') {
            event.respondWith(handleMutationRequest(event.request));
        }
        return;
    }

    // Estrategia según el tipo de recurso
    if (isStaticAsset(url)) {
        // Cache First para estáticos
        event.respondWith(cacheFirst(event.request));
    } else if (isAPIRequest(url)) {
        // Network First para API, con fallback a cache
        event.respondWith(networkFirstWithCache(event.request));
    } else if (isOfflineRoute(url)) {
        // Network First para páginas, con fallback offline
        event.respondWith(networkFirstWithOffline(event.request));
    } else {
        // Default: intentar red, si falla usar cache
        event.respondWith(networkFirst(event.request));
    }
});

// ============================================================================
// ESTRATEGIAS DE CACHE
// ============================================================================

/**
 * Cache First - Para archivos estáticos
 */
async function cacheFirst(request) {
    const cached = await caches.match(request);
    if (cached) {
        return cached;
    }

    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(STATIC_CACHE);
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        console.error('[SW] Error en cacheFirst:', error);
        return new Response('Recurso no disponible offline', { status: 503 });
    }
}

/**
 * Network First - Para contenido dinámico
 */
async function networkFirst(request) {
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(DYNAMIC_CACHE);
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        const cached = await caches.match(request);
        if (cached) {
            return cached;
        }
        throw error;
    }
}

/**
 * Network First con cache de datos para API
 */
async function networkFirstWithCache(request) {
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(DATA_CACHE);
            cache.put(request, response.clone());

            // Notificar al cliente que hay datos nuevos
            notifyClients({ type: 'DATA_UPDATED', url: request.url });
        }
        return response;
    } catch (error) {
        console.log('[SW] Sin conexión, usando cache para:', request.url);
        const cached = await caches.match(request);
        if (cached) {
            // Agregar header para indicar que es del cache
            const headers = new Headers(cached.headers);
            headers.set('X-From-Cache', 'true');
            return new Response(cached.body, {
                status: cached.status,
                statusText: cached.statusText,
                headers: headers
            });
        }

        // Retornar respuesta vacía si no hay cache
        return new Response(JSON.stringify({
            offline: true,
            error: 'Sin conexión y sin datos en cache'
        }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' }
        });
    }
}

/**
 * Network First con página offline de fallback
 */
async function networkFirstWithOffline(request) {
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(DYNAMIC_CACHE);
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        console.log('[SW] Sin conexión, buscando en cache:', request.url);

        // Intentar cache
        const cached = await caches.match(request);
        if (cached) {
            return cached;
        }

        // Mostrar página offline
        const offlinePage = await caches.match('/offline');
        if (offlinePage) {
            return offlinePage;
        }

        // Fallback HTML básico
        return new Response(`
            <!DOCTYPE html>
            <html lang="es">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>OBYRA - Sin Conexión</title>
                <style>
                    body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #1a1a2e; color: #fff; }
                    .container { max-width: 400px; margin: 0 auto; }
                    .icon { font-size: 64px; margin-bottom: 20px; }
                    h1 { color: #00d9ff; }
                    p { color: #ccc; }
                    .btn { background: #00d9ff; color: #000; padding: 12px 24px; border: none; border-radius: 8px; cursor: pointer; margin-top: 20px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="icon">📡</div>
                    <h1>Sin Conexión</h1>
                    <p>No hay conexión a internet. Los cambios se guardarán localmente y se sincronizarán cuando vuelvas a estar online.</p>
                    <button class="btn" onclick="location.reload()">Reintentar</button>
                </div>
            </body>
            </html>
        `, {
            status: 200,
            headers: { 'Content-Type': 'text/html' }
        });
    }
}

/**
 * Manejar peticiones de mutación (POST, PUT, DELETE)
 */
async function handleMutationRequest(request) {
    try {
        const response = await fetch(request.clone());
        return response;
    } catch (error) {
        console.log('[SW] Guardando operación para sincronizar:', request.url);

        // Clonar el request para leer el body
        const clonedRequest = request.clone();
        const body = await clonedRequest.text();

        // Guardar en la cola de sincronización
        await saveToSyncQueue({
            url: request.url,
            method: request.method,
            headers: Object.fromEntries(request.headers.entries()),
            body: body,
            timestamp: Date.now()
        });

        // Notificar al cliente
        notifyClients({
            type: 'QUEUED_FOR_SYNC',
            url: request.url,
            method: request.method
        });

        // Retornar respuesta indicando que se guardó offline
        return new Response(JSON.stringify({
            offline: true,
            queued: true,
            message: 'Guardado localmente. Se sincronizará cuando haya conexión.'
        }), {
            status: 202, // Accepted
            headers: { 'Content-Type': 'application/json' }
        });
    }
}

// ============================================================================
// SINCRONIZACIÓN EN BACKGROUND
// ============================================================================
self.addEventListener('sync', (event) => {
    console.log('[SW] Evento de sincronización:', event.tag);

    if (event.tag === 'sync-pending-operations') {
        event.waitUntil(syncPendingOperations());
    }
});

async function syncPendingOperations() {
    console.log('[SW] Sincronizando operaciones pendientes...');

    const queue = await getSyncQueue();

    for (const operation of queue) {
        try {
            const response = await fetch(operation.url, {
                method: operation.method,
                headers: operation.headers,
                body: operation.body
            });

            if (response.ok) {
                await removeFromSyncQueue(operation.id);
                notifyClients({
                    type: 'SYNC_SUCCESS',
                    url: operation.url,
                    method: operation.method
                });
            }
        } catch (error) {
            console.error('[SW] Error sincronizando:', operation.url, error);
            // Se reintentará en la próxima sincronización
        }
    }
}

// ============================================================================
// MENSAJES DESDE EL CLIENTE
// ============================================================================
self.addEventListener('message', (event) => {
    const { type, data } = event.data;

    switch (type) {
        case 'SKIP_WAITING':
            self.skipWaiting();
            break;

        case 'CACHE_URLS':
            // Cachear URLs específicas bajo demanda
            cacheUrls(data.urls);
            break;

        case 'CLEAR_CACHE':
            clearAllCaches();
            break;

        case 'GET_SYNC_QUEUE':
            getSyncQueue().then(queue => {
                event.ports[0].postMessage({ queue });
            });
            break;

        case 'FORCE_SYNC':
            syncPendingOperations();
            break;
    }
});

// ============================================================================
// UTILIDADES
// ============================================================================

function isStaticAsset(url) {
    return url.pathname.startsWith('/static/') ||
           url.pathname.endsWith('.css') ||
           url.pathname.endsWith('.js') ||
           url.pathname.endsWith('.png') ||
           url.pathname.endsWith('.jpg') ||
           url.pathname.endsWith('.ico') ||
           url.pathname.endsWith('.woff2');
}

function isAPIRequest(url) {
    return url.pathname.startsWith('/api/');
}

function isOfflineRoute(url) {
    return OFFLINE_ROUTES.some(route => url.pathname.startsWith(route));
}

async function cacheUrls(urls) {
    const cache = await caches.open(DYNAMIC_CACHE);
    for (const url of urls) {
        try {
            await cache.add(url);
            console.log('[SW] URL cacheada:', url);
        } catch (error) {
            console.warn('[SW] Error cacheando:', url, error);
        }
    }
}

async function clearAllCaches() {
    const cacheNames = await caches.keys();
    await Promise.all(cacheNames.map(name => caches.delete(name)));
    console.log('[SW] Todos los caches eliminados');
}

function notifyClients(message) {
    self.clients.matchAll().then(clients => {
        clients.forEach(client => client.postMessage(message));
    });
}

// Cola de sincronización usando IndexedDB del SW
const DB_NAME = 'obyra-sync-queue';
const STORE_NAME = 'operations';

async function openSyncDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, 1);

        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);

        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
            }
        };
    });
}

async function saveToSyncQueue(operation) {
    const db = await openSyncDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        const store = tx.objectStore(STORE_NAME);
        const request = store.add(operation);

        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

async function getSyncQueue() {
    const db = await openSyncDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readonly');
        const store = tx.objectStore(STORE_NAME);
        const request = store.getAll();

        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

async function removeFromSyncQueue(id) {
    const db = await openSyncDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        const store = tx.objectStore(STORE_NAME);
        const request = store.delete(id);

        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
    });
}

console.log('[SW] Service Worker cargado - OBYRA Offline Mode');
