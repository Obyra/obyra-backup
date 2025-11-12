# 📄 Configuración de Facturación - OBYRA

Este documento explica cómo configurar el sistema de facturación automática cuando tengas la empresa constituida legalmente.

## 📋 Requisitos Previos

Antes de configurar la facturación, necesitás tener:

### 1. Empresa Constituida
- [ ] Razón Social definida (SAS, SRL, SA, etc.)
- [ ] CUIT de la empresa
- [ ] Inscripción en AFIP
- [ ] Condición frente al IVA definida (Responsable Inscripto, Monotributista, etc.)

### 2. Facturación Electrónica AFIP
- [ ] Alta en régimen de factura electrónica en AFIP
- [ ] Certificado digital (.crt) obtenido
- [ ] Clave privada (.key) generada
- [ ] Punto de venta asignado por AFIP
- [ ] Homologación realizada (testing)

### 3. Cuenta Bancaria
- [ ] Cuenta bancaria empresarial
- [ ] CBU
- [ ] Alias (opcional pero recomendado)

### 4. Logo y Diseño
- [ ] Logo de la empresa en formato PNG o JPG
- [ ] Tamaño recomendado: 400x200px
- [ ] Fondo transparente (PNG)

## 🔧 Configuración Paso a Paso

### Paso 1: Datos Básicos de la Empresa

Editá tu archivo `.env` (o crea uno desde `.env.example`):

```env
# Datos de la empresa
BILLING_COMPANY_NAME=OBYRA S.A.S.
BILLING_COMPANY_TAX_ID=30-12345678-9      # Tu CUIT
BILLING_COMPANY_TAX_CONDITION=Responsable Inscripto
BILLING_COMPANY_ADDRESS=Av. Corrientes 1234
BILLING_COMPANY_CITY=Buenos Aires
BILLING_COMPANY_PROVINCE=CABA
BILLING_COMPANY_POSTAL_CODE=C1043
BILLING_COMPANY_EMAIL=facturacion@obyra.com
BILLING_COMPANY_PHONE=+54 11 1234-5678
BILLING_COMPANY_START_DATE=01/01/2025
```

### Paso 2: Configurar AFIP (Facturación Electrónica)

#### 2.1 Obtener Certificado AFIP

1. Ingresá a [AFIP](https://www.afip.gob.ar)
2. Andá a "Administrador de Relaciones de Clave Fiscal"
3. Generá el certificado para "Factura Electrónica"
4. Descargá el certificado (.crt) y la clave privada (.key)
5. Guardá los archivos en una carpeta segura del proyecto (ej: `certificates/`)

#### 2.2 Configurar Variables

```env
# AFIP - Facturación Electrónica
BILLING_AFIP_ENABLED=true
BILLING_AFIP_CUIT=30123456789              # Tu CUIT (sin guiones)
BILLING_AFIP_CERT_PATH=certificates/obyra.crt
BILLING_AFIP_KEY_PATH=certificates/obyra.key
BILLING_AFIP_PRODUCTION=false              # Empezar con false (homologación)
BILLING_AFIP_POS=00001                     # Tu punto de venta
```

#### 2.3 Testear en Homologación

Antes de pasar a producción:

1. Configurá `BILLING_AFIP_PRODUCTION=false`
2. Probá generar facturas de prueba
3. Verificá que se autorizen correctamente en el sitio de homologación de AFIP
4. Una vez que funcione todo, cambiá a `BILLING_AFIP_PRODUCTION=true`

### Paso 3: Datos Bancarios

```env
# Datos bancarios para transferencias
BILLING_BANK_CBU=0123456789012345678901
BILLING_BANK_ALIAS=obyra.facturacion
BILLING_BANK_NAME=Banco Galicia
```

Estos datos aparecerán en las facturas para que los clientes puedan pagar por transferencia.

### Paso 4: Logo de la Empresa

1. Prepará tu logo (recomendado: PNG con fondo transparente, 400x200px)
2. Guardá el archivo en: `static/images/logo-factura.png`
3. O configurá una ruta personalizada:

```env
BILLING_COMPANY_LOGO_PATH=images/mi-logo-personalizado.png
```

### Paso 5: Configuración Adicional

```env
# IVA (21% en Argentina, cambiar si corresponde otro porcentaje)
BILLING_IVA_PERCENTAGE=21.0

# Día del mes para facturación automática (1 = primer día del mes)
BILLING_DAY_OF_MONTH=1

# Mensaje personalizado en el pie de página de la factura
BILLING_INVOICE_FOOTER_TEXT=Gracias por confiar en OBYRA - Tu partner en gestión de obras
```

## 🔄 Facturación Automática

### ¿Cómo Funciona?

El sistema está preparado para:

1. **Facturación Mensual Automática**:
   - Cada día configurado (`BILLING_DAY_OF_MONTH`) se ejecuta un proceso automático
   - Se generan facturas para todos los usuarios con planes activos
   - Se envían por email automáticamente

2. **Débito Automático** (con Mercado Pago):
   - Si el usuario tiene tarjeta guardada, se debita automáticamente
   - Si el débito es exitoso, se marca la factura como pagada
   - Si falla, se envía notificación al usuario

3. **Envío de Facturas**:
   - Las facturas se envían al email del usuario
   - Incluyen PDF adjunto
   - Link para descargar desde el sistema

### Configurar Mercado Pago (ya configurado en el sistema)

El sistema ya tiene integración con Mercado Pago. Solo asegurate de tener:

```env
MP_ACCESS_TOKEN=tu_access_token_de_mercado_pago
MP_WEBHOOK_PUBLIC_URL=https://tu-dominio.com
```

## 📊 Verificar Configuración

Podés verificar que todo está bien configurado con:

```python
from config.billing_config import BILLING

# Verificar si la configuración está completa
if BILLING.is_configured():
    print("✅ Configuración de facturación completa")
    info = BILLING.get_company_info()
    print(f"Empresa: {info['name']}")
    print(f"CUIT: {info['tax_id']}")
else:
    print("❌ Faltan datos de facturación")
```

## 🚨 Importante

### Seguridad
- ❗ **NUNCA** commitees el archivo `.env` a git
- ❗ Los certificados de AFIP deben estar en `.gitignore`
- ❗ Mantené las credenciales seguras
- ❗ En producción, usá `SESSION_COOKIE_SECURE=true`

### Cumplimiento Legal
- ✅ Asegurate de cumplir con todas las obligaciones fiscales
- ✅ Consultá con un contador para configuración de IVA
- ✅ Verificá que tu empresa esté habilitada para facturación electrónica
- ✅ Guardá backup de todas las facturas generadas

### Homologación AFIP
- ⚠️ **SIEMPRE** testeá primero en homologación
- ⚠️ No pases a producción hasta estar 100% seguro
- ⚠️ Las facturas en producción tienen validez legal

## 📞 Soporte

Si tenés dudas sobre:
- **AFIP**: Consultá con tu contador o llamá al 0800-999-2347
- **Mercado Pago**: https://www.mercadopago.com.ar/developers
- **Sistema OBYRA**: Revisá la documentación técnica

## ✅ Checklist Final

Antes de activar facturación en producción:

- [ ] Todos los datos de la empresa están completos y correctos
- [ ] Certificado AFIP obtenido y configurado
- [ ] Homologación exitosa (facturas de prueba autorizadas)
- [ ] Logo de la empresa en la carpeta correcta
- [ ] Datos bancarios correctos
- [ ] IVA configurado correctamente
- [ ] Email de facturación funcionando
- [ ] Mercado Pago configurado (si aplica)
- [ ] Backup de certificados en lugar seguro
- [ ] Contador/a notificado del inicio de facturación electrónica
- [ ] `.env` en `.gitignore`
- [ ] `BILLING_AFIP_PRODUCTION=true` solo cuando todo esté listo

---

**¡Listo!** Una vez completados estos pasos, el sistema facturará automáticamente todos los meses. 🎉
