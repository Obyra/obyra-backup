"""
Seed de demo para los 4 dashboards por rol.
=================================================================
Crea una organizacion con un usuario por rol (admin/pm/tecnico/operario),
una obra con datos suficientes para que cada dashboard muestre contenido,
y las asignaciones que ejercitan el fix del PM (el tecnico se asigna como
'operario', no debe aparecer "gestionando").

Uso (dentro del contenedor de la app):
    docker exec -it obyra-app-dev python scripts/seed_dashboards_demo.py

Idempotente: si el usuario admin de demo ya existe, no duplica nada.

Credenciales creadas (password para los 4): Obyra1234
    admin@obyra.local · pm@obyra.local · tecnico@obyra.local · operario@obyra.local
"""
import os
import sys
from datetime import date, timedelta

# permitir ejecutar desde la raiz del repo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as _app_module
from extensions import db

PASSWORD = "Obyra1234"


def run():
    app = _app_module.app
    with app.app_context():
        from models.core import Organizacion, Usuario, OrgMembership
        from models.projects import (
            Obra, AsignacionObra, EtapaObra, TareaEtapa,
        )

        if Usuario.query.filter_by(email="admin@obyra.local").first():
            print("[seed] La demo ya existe (admin@obyra.local). Nada que hacer.")
            return

        org = Organizacion(
            nombre="Constructora Demo",
            plan_tipo="premium", max_usuarios=999, max_obras=999,
            fecha_fin_plan=date.today() + timedelta(days=365),
        )
        db.session.add(org)
        db.session.flush()

        def mk_user(nombre, email, role):
            u = Usuario(nombre=nombre, apellido="Demo", email=email, role=role,
                        organizacion_id=org.id, primary_org_id=org.id, activo=True)
            u.set_password(PASSWORD)
            db.session.add(u)
            db.session.flush()
            # La membresia guarda el MISMO rol -> el loader (ya corregido) lo respeta.
            db.session.add(OrgMembership(org_id=org.id, user_id=u.id, role=role, status="active"))
            return u

        admin = mk_user("Ana", "admin@obyra.local", "admin")
        pm = mk_user("Pedro", "pm@obyra.local", "pm")
        tec = mk_user("Tomas", "tecnico@obyra.local", "tecnico")
        ope = mk_user("Oscar", "operario@obyra.local", "operario")

        # Obra atrasada (fecha_fin vencida + avance < 100) -> estado_operativo ATRASADA
        obra = Obra(
            nombre="Edificio Demo", cliente="Cliente Demo", organizacion_id=org.id,
            estado="en_curso", presupuesto_total=1500000, costo_real=0, progreso=45,
            fecha_inicio=date.today() - timedelta(days=45),
            fecha_fin_estimada=date.today() - timedelta(days=3),
        )
        db.session.add(obra)
        db.session.flush()

        # PM gestiona (rol de gestion); Tecnico solo asignado como operario.
        db.session.add(AsignacionObra(obra_id=obra.id, usuario_id=pm.id, rol_en_obra="pm", activo=True))
        db.session.add(AsignacionObra(obra_id=obra.id, usuario_id=tec.id, rol_en_obra="operario", activo=True))

        etapa = EtapaObra(obra_id=obra.id, nombre="Estructura", estado="en_curso", orden=1)
        db.session.add(etapa)
        db.session.flush()
        db.session.add(TareaEtapa(
            etapa_id=etapa.id, nombre="Colar losa 3er piso", estado="en_curso",
            responsable_id=ope.id, fecha_fin_plan=date.today() - timedelta(days=1),
        ))
        db.session.add(TareaEtapa(
            etapa_id=etapa.id, nombre="Encofrado columnas", estado="pendiente",
            responsable_id=ope.id, fecha_fin_plan=date.today() + timedelta(days=5),
        ))

        db.session.commit()
        print("[seed] OK. Org=%d  admin=%d pm=%d tecnico=%d operario=%d  obra=%d" % (
            org.id, admin.id, pm.id, tec.id, ope.id, obra.id))
        print("[seed] Login: admin@obyra.local / pm@obyra.local / tecnico@obyra.local / operario@obyra.local")
        print("[seed] Password para los 4: %s" % PASSWORD)


if __name__ == "__main__":
    run()
