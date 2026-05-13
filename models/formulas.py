"""
Biblioteca de Fórmulas Técnicas y Coeficientes - Fase 1 del Plan 90%
=====================================================================

Persistencia de la biblioteca técnica importada desde el Excel
`OBYRA_Biblioteca_Formulas_Computos_DETALLADA_SIN_PRECIOS.xlsx`.

IMPORTANTE: en Fase 1 estas tablas NO se conectan con presupuestos/calc IA.
Solo se cargan y se exponen via UI read-only del super admin para validar
que el motor consume datos correctos antes de cambiar logica de calculo.

Modelos:
  - FormulaTecnica: codigo + rubro + expresion tecnica + inputs requeridos.
    Cada fila del Excel se convierte en una FormulaTecnica.
  - Coeficiente: parametros editables (mermas, dosificaciones, rendimientos
    de mano de obra, rendimientos de equipo, capacidades de flete, etc.).
    Modelo hibrido: organizacion_id NULL = global OBYRA (valor default
    para todos los tenants), valor seteado = override privado del tenant.
"""
from datetime import datetime

from extensions import db


class FormulaTecnica(db.Model):
    """Fórmula técnica de cómputo, APU o presupuesto.

    Cada fila del Excel `OBYRA_Biblioteca_Formulas_Computos_*.xlsx` se
    materializa en una de estas filas.

    Ejemplos:
      HOR-001  Hormigón en bases/zapatas  m³ = LARGO*ANCHO*ALTURA*CANTIDAD
      MAM-004  Ladrillos / bloques        un = M2_NETO*UNIDADES_M2
      MO-001   Jornales por rendimiento   jornales = CANTIDAD_OBRA/RENDIMIENTO_DIARIO
    """

    __tablename__ = 'formulas_tecnicas'

    id = db.Column(db.Integer, primary_key=True)

    # Codigo unico del Excel: GEN-001, HOR-007, MAM-004, etc.
    # UNIQUE solo para globales (organizacion_id IS NULL) — los overrides por
    # tenant pueden reutilizar el codigo. La restriccion de unicidad efectiva
    # se hace en runtime_migrations con un partial UNIQUE INDEX.
    codigo = db.Column(db.String(40), nullable=False, index=True)

    # Rubro: General, Hormigon, Acero, Mamposteria, Mano de obra, Equipos, etc.
    rubro = db.Column(db.String(80), nullable=False, index=True)

    # Item / concepto: descripcion humana corta.
    item_concepto = db.Column(db.String(300), nullable=False)

    # Unidad de salida: m2, m3, kg, jornales, moneda, etc.
    unidad_salida = db.Column(db.String(40))

    # Formula tecnica en texto humano (para auditoria/UI):
    # "m³ = largo × ancho × alto"
    formula_texto = db.Column(db.Text)

    # Expresion evaluable por el motor (Fase 2):
    # "LARGO*ANCHO*ALTO" -> evaluable con sustitucion de variables.
    formula_expr = db.Column(db.Text)

    # Lista JSON de inputs requeridos: ["largo", "ancho", "alto"].
    # En Fase 1 se guarda como string crudo del Excel; el evaluador lo parsea
    # en Fase 2.
    inputs_requeridos = db.Column(db.Text)

    # Si la formula usa al menos 1 coeficiente editable (Si/No del Excel).
    usa_coeficiente_editable = db.Column(db.Boolean, default=False, nullable=False,
                                          server_default=db.text('false'))

    # Categoria del calculo:
    #   'cantidad'       -> calcula cantidades de obra (m2, m3, ml, un)
    #   'consumo_insumo' -> calcula consumo de insumos (kg cemento, bolsas, etc.)
    #   'apu'            -> arma APU (precios unitarios)
    #   'presupuesto'    -> totales del presupuesto (CD, IND, GG, IVA)
    #   'avance'         -> avance, certificacion, desvios
    categoria_calculo = db.Column(db.String(40), index=True)

    # "Que calcula" + observaciones del Excel.
    que_calcula = db.Column(db.Text)
    observaciones = db.Column(db.Text)

    # Trazabilidad: que hoja del Excel y que orden tenia.
    hoja_origen = db.Column(db.String(80))
    orden = db.Column(db.Integer, default=0)

    # Activa: permite desactivar formulas obsoletas sin borrar (auditoria).
    activa = db.Column(db.Boolean, default=True, nullable=False,
                       server_default=db.text('true'))

    # Multi-tenant: NULL = formula global curada por OBYRA, visible a todos.
    # Valor seteado = override privado del tenant (Fase 5).
    organizacion_id = db.Column(db.Integer,
                                 db.ForeignKey('organizaciones.id', ondelete='CASCADE'),
                                 nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                            onupdate=datetime.utcnow, nullable=False)

    # Trazabilidad del ultimo import batch (idempotencia).
    batch_id = db.Column(db.String(40), nullable=True)

    organizacion = db.relationship('Organizacion', foreign_keys=[organizacion_id])

    def __repr__(self):
        return f'<FormulaTecnica {self.codigo} {self.item_concepto[:40]}>'

    @property
    def is_global(self):
        return self.organizacion_id is None

    def to_dict(self):
        return {
            'id': self.id,
            'codigo': self.codigo,
            'rubro': self.rubro,
            'item_concepto': self.item_concepto,
            'unidad_salida': self.unidad_salida,
            'formula_texto': self.formula_texto,
            'formula_expr': self.formula_expr,
            'inputs_requeridos': self.inputs_requeridos,
            'usa_coeficiente_editable': self.usa_coeficiente_editable,
            'categoria_calculo': self.categoria_calculo,
            'que_calcula': self.que_calcula,
            'observaciones': self.observaciones,
            'hoja_origen': self.hoja_origen,
            'orden': self.orden,
            'activa': self.activa,
            'is_global': self.is_global,
            'organizacion_id': self.organizacion_id,
        }


class Coeficiente(db.Model):
    """Coeficiente tecnico editable.

    Mermas, dosificaciones, rendimientos de mano de obra/equipos, capacidades
    de flete, pesos especificos, rendimientos de productos, etc.

    Modelo hibrido (multi-tenant):
      - organizacion_id IS NULL  -> coeficiente global curado por OBYRA,
        es el valor default visible a todos los tenants.
      - organizacion_id seteado  -> override privado del tenant (Fase 5).

    Cuando la calc/APU consulta un coeficiente, hace fallback en este orden:
      1. Coeficiente con organizacion_id=tenant_actual (override).
      2. Coeficiente con organizacion_id=NULL (global).

    Ejemplos:
      MERMA_LADRILLO        merma          0.08    fraccion   Mamposteria
      KG_CEMENTO_M3_H21     dosificacion   350     kg/m3      Hormigon
      REND_REVOQUE_M2_DIA   rendimiento_mo 12      m2/dia     Revoques
    """

    __tablename__ = 'coeficientes_tecnicos'

    id = db.Column(db.Integer, primary_key=True)

    # Codigo unico (solo para globales; igual que FormulaTecnica).
    codigo = db.Column(db.String(80), nullable=False, index=True)

    # Tipo de coeficiente (categoriza para UI y para que el motor lo busque):
    #   'merma'              -> merma_ladrillo, merma_hormigon, etc.
    #   'dosificacion'       -> kg_cemento_m3, m3_arena_m3, kg_cal_m3
    #   'rendimiento_mo'     -> m2/dia, m3/dia, ml/dia
    #   'rendimiento_equipo' -> m3/h, viajes/dia
    #   'capacidad_flete'    -> m3 o kg por viaje
    #   'peso_especifico'    -> kg/m3
    #   'rendimiento_pintura'-> m2/litro/mano
    #   'rendimiento_pieza'  -> m2/caja, un/m2, etc.
    #   'horas_jornal'       -> horas por jornal (default 8)
    #   'porcentaje_indirectos' / 'porcentaje_gg' / 'porcentaje_beneficio'
    #   'alicuota_iva'
    tipo = db.Column(db.String(40), nullable=False, index=True)

    # Nombre humano: "Merma para ladrillo comun", "Dosificacion H21 cemento".
    descripcion = db.Column(db.String(300))

    # Valor por defecto (puede ser fraccion como 0.08, entero como 350, etc.).
    valor_default = db.Column(db.Numeric(15, 6), nullable=False, default=0)

    # Unidad: %, kg/m³, m²/día, fraccion, etc.
    unidad = db.Column(db.String(40))

    # Rubro al que aplica (opcional): Mamposteria, Hormigon, Revoques, etc.
    rubro = db.Column(db.String(80), index=True)

    # Aplicable a: H21, ladrillo comun, mortero 1:3, etc.
    # Permite tener varios coef con el mismo tipo (ej. kg_cemento_m3 con
    # valor distinto segun el tipo de hormigon).
    aplicable_a = db.Column(db.String(120))

    # Notas y referencia.
    notas = db.Column(db.Text)

    # Activo: permite desactivar sin borrar.
    activo = db.Column(db.Boolean, default=True, nullable=False,
                        server_default=db.text('true'))

    # Multi-tenant.
    organizacion_id = db.Column(db.Integer,
                                 db.ForeignKey('organizaciones.id', ondelete='CASCADE'),
                                 nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                            onupdate=datetime.utcnow, nullable=False)

    batch_id = db.Column(db.String(40), nullable=True)

    organizacion = db.relationship('Organizacion', foreign_keys=[organizacion_id])

    def __repr__(self):
        return (
            f'<Coeficiente {self.codigo} '
            f'{self.valor_default}{self.unidad or ""}>'
        )

    @property
    def is_global(self):
        return self.organizacion_id is None

    def to_dict(self):
        return {
            'id': self.id,
            'codigo': self.codigo,
            'tipo': self.tipo,
            'descripcion': self.descripcion,
            'valor_default': float(self.valor_default) if self.valor_default is not None else 0,
            'unidad': self.unidad,
            'rubro': self.rubro,
            'aplicable_a': self.aplicable_a,
            'notas': self.notas,
            'activo': self.activo,
            'is_global': self.is_global,
            'organizacion_id': self.organizacion_id,
        }


class ImportBatchFormulas(db.Model):
    """Batch de import de la biblioteca de formulas para trazabilidad.

    Cada import del Excel registra un batch con contadores + checksum del
    archivo. Si el super admin se equivoca puede deshacer un batch
    (Fase 1 no incluye undo, solo registro).
    """

    __tablename__ = 'import_batches_formulas'

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.String(40), unique=True, nullable=False, index=True)
    filename = db.Column(db.String(255))
    checksum = db.Column(db.String(80))  # sha256 del archivo
    estado = db.Column(db.String(20), nullable=False, default='en_curso')
    # contadores
    formulas_creadas = db.Column(db.Integer, default=0)
    formulas_actualizadas = db.Column(db.Integer, default=0)
    coeficientes_creados = db.Column(db.Integer, default=0)
    coeficientes_actualizados = db.Column(db.Integer, default=0)
    invalidos = db.Column(db.Integer, default=0)
    errores_json = db.Column(db.Text)
    # auditoria
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    finished_at = db.Column(db.DateTime, nullable=True)
    started_by_user_id = db.Column(db.Integer,
                                    db.ForeignKey('usuarios.id', ondelete='SET NULL'),
                                    nullable=True)

    def __repr__(self):
        return f'<ImportBatchFormulas {self.batch_id} {self.estado}>'
