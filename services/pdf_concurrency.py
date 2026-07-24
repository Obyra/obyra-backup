# -*- coding: utf-8 -*-
"""Cupo de concurrencia para render de PDF (defensa contra DoS por CPU).

WeasyPrint es CPU-intensivo (~2-5s por PDF). Sin limite, unos pocos renders
concurrentes saturan la CPU y voltean el worker web. Aca limitamos cuantos renders
corren a la vez POR PROCESO (gunicorn) con un semaforo:

  - render_pdf_into(): para VISTAS. Non-blocking -> si no hay cupo NO encola (evita
    apilar CPU): devuelve un Response 503 que la vista retorna tal cual (load-shed).
  - pdf_render_lock(): para helpers que NO son vista (no pueden devolver 503):
    espera un cupo hasta `timeout`s (serializa, protege CPU).

Cupo configurable por env PDF_MAX_CONCURRENT (default 2 por proceso). El semaforo es
per-process: con N workers de gunicorn, el maximo real de renders concurrentes es
N * PDF_MAX_CONCURRENT, pero cada exceso se rechaza rapido en vez de encolarse.
"""
import os
import threading
from contextlib import contextmanager


def _max_concurrent():
    try:
        return max(1, int(os.getenv('PDF_MAX_CONCURRENT', '2')))
    except (TypeError, ValueError):
        return 2


_sem = threading.BoundedSemaphore(_max_concurrent())


def pdf_busy_response():
    """Respuesta 503 con Retry-After para cuando no hay cupo de render."""
    from flask import jsonify
    resp = jsonify({'ok': False,
                    'error': 'El servidor esta generando otros PDFs en este momento. '
                             'Reintenta en unos segundos.'})
    resp.status_code = 503
    resp.headers['Retry-After'] = '5'
    return resp


def render_pdf_into(target, html_string, **kwargs):
    """Render de PDF con cupo (para usar dentro de una vista).

    Non-blocking: si no hay cupo, devuelve un Response 503 (load-shedding). Si hay
    cupo, escribe el PDF en `target` y devuelve None. Uso:

        r = render_pdf_into(pdf_buffer, html_string, presentational_hints=True)
        if r is not None:
            return r
        pdf_buffer.seek(0)
        return send_file(pdf_buffer, ...)
    """
    if not _sem.acquire(blocking=False):
        return pdf_busy_response()
    try:
        from weasyprint import HTML
        HTML(string=html_string).write_pdf(target, **kwargs)
    finally:
        _sem.release()
    return None


@contextmanager
def pdf_render_lock(timeout=90):
    """Cupo de render para codigo que NO es una vista (no puede devolver 503).

    Bloquea hasta obtener un cupo o `timeout`s. Yield True si lo obtuvo, False si
    expiro. El caller decide que hacer si es False (ej. raise)."""
    got = _sem.acquire(blocking=True, timeout=timeout)
    try:
        yield got
    finally:
        if got:
            _sem.release()
