"""
Legacy: cotizar materiales via WhatsApp desde items del pliego.

ESTE FLUJO FUE REEMPLAZADO por el circuito del Presupuesto Ejecutivo
(blueprint_presupuestos/ejecutivo.py). El pliego del cliente describe
rubros/titulos contractuales ("Personal de Supervisión", "Control de
Accesos", etc.) — esos NO son materiales y no tiene sentido asignarles
un proveedor. Los materiales reales viven en las composiciones del
ejecutivo, donde se consolidan y se cotizan correctamente.

La ruta /presupuestos/<id>/cotizar-wa queda como redirect para no romper
bookmarks antiguos. Apunta a /ejecutivo (entrada principal del flujo
correcto).

Los endpoints de editar/vincular/generar fueron eliminados. Las tablas
SolicitudCotizacionWA e ItemPresupuestoProveedor quedan en DB por
historial auditivo pero ya no se usan.
"""
from flask import redirect, url_for, flash
from flask_login import login_required

from blueprint_presupuestos import presupuestos_bp


@presupuestos_bp.route('/<int:presupuesto_id>/cotizar-wa')
@login_required
def cotizar_wa_vista(presupuesto_id):
    """Deprecado. Redirige al flujo correcto (Ejecutivo)."""
    flash(
        'La cotización por WhatsApp se gestiona desde el Ejecutivo. '
        'Desglosá los rubros del pliego en materiales, MO y equipos; '
        'después vas a "Recursos a cotizar" para pedir precios.',
        'info',
    )
    return redirect(url_for('presupuestos.ejecutivo_vista', id=presupuesto_id))
