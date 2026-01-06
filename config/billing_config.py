"""
Configuración de facturación para OBYRA
Completar cuando se tenga la empresa constituida legalmente
"""
import os
from typing import Optional

class BillingConfig:
    """
    Configuración de datos de facturación de la empresa

    IMPORTANTE: Completar estos datos cuando tengas la empresa constituida
    """

    # ============================================
    # DATOS DE LA EMPRESA (COMPLETAR)
    # ============================================

    # Razón Social
    COMPANY_NAME: str = os.getenv('BILLING_COMPANY_NAME', 'OBYRA S.A.S.')  # Cambiar cuando tengas la razón social

    # CUIT/CUIL de la empresa
    COMPANY_TAX_ID: str = os.getenv('BILLING_COMPANY_TAX_ID', '')  # Formato: XX-XXXXXXXX-X

    # Condición frente al IVA
    COMPANY_TAX_CONDITION: str = os.getenv('BILLING_COMPANY_TAX_CONDITION', 'Responsable Inscripto')
    # Opciones: 'Responsable Inscripto', 'Monotributista', 'Exento'

    # Domicilio fiscal
    COMPANY_ADDRESS: str = os.getenv('BILLING_COMPANY_ADDRESS', '')
    COMPANY_CITY: str = os.getenv('BILLING_COMPANY_CITY', '')
    COMPANY_PROVINCE: str = os.getenv('BILLING_COMPANY_PROVINCE', '')
    COMPANY_POSTAL_CODE: str = os.getenv('BILLING_COMPANY_POSTAL_CODE', '')

    # Contacto
    COMPANY_EMAIL: str = os.getenv('BILLING_COMPANY_EMAIL', 'facturacion@obyra.com')
    COMPANY_PHONE: str = os.getenv('BILLING_COMPANY_PHONE', '')

    # Punto de venta AFIP
    AFIP_POS: str = os.getenv('BILLING_AFIP_POS', '00001')  # Punto de venta

    # Inicio de actividades
    COMPANY_START_DATE: str = os.getenv('BILLING_COMPANY_START_DATE', '')  # Formato: DD/MM/YYYY

    # ============================================
    # CONFIGURACIÓN DE FACTURACIÓN ELECTRÓNICA
    # ============================================

    # AFIP Web Service (para facturación electrónica)
    AFIP_ENABLED: bool = os.getenv('BILLING_AFIP_ENABLED', 'false').lower() == 'true'
    AFIP_CUIT: str = os.getenv('BILLING_AFIP_CUIT', '')
    AFIP_CERT_PATH: str = os.getenv('BILLING_AFIP_CERT_PATH', '')  # Certificado .crt
    AFIP_KEY_PATH: str = os.getenv('BILLING_AFIP_KEY_PATH', '')    # Clave privada .key
    AFIP_PRODUCTION: bool = os.getenv('BILLING_AFIP_PRODUCTION', 'false').lower() == 'true'

    # ============================================
    # CONFIGURACIÓN DE PLANTILLAS DE FACTURA
    # ============================================

    # Logo de la empresa (ruta relativa desde static/)
    COMPANY_LOGO_PATH: str = os.getenv('BILLING_COMPANY_LOGO_PATH', 'images/logo-factura.png')

    # Pie de página personalizado
    INVOICE_FOOTER_TEXT: str = os.getenv('BILLING_INVOICE_FOOTER_TEXT',
        'Gracias por confiar en OBYRA - Software de gestión de obras')

    # ============================================
    # CONFIGURACIÓN DE PLANES Y PRECIOS
    # ============================================

    # IVA aplicable (21% en Argentina)
    IVA_PERCENTAGE: float = float(os.getenv('BILLING_IVA_PERCENTAGE', '21.0'))

    # Día del mes para facturación automática
    BILLING_DAY_OF_MONTH: int = int(os.getenv('BILLING_DAY_OF_MONTH', '1'))

    # ============================================
    # MÉTODOS DE PAGO
    # ============================================

    # Mercado Pago (ya configurado en app.py)
    MP_ENABLED: bool = bool(os.getenv('MP_ACCESS_TOKEN', '').strip())

    # Transferencias bancarias habilitadas
    BANK_TRANSFER_ENABLED: bool = True

    # Datos del titular
    BANK_HOLDER_NAME: str = 'Brenda Priscila Koldobsky'
    BANK_HOLDER_DNI: str = '34722707'
    BANK_NAME: str = 'Banco Galicia'

    # Cuenta en DÓLARES (USD)
    BANK_USD_CBU: str = '0070104031004008448459'
    BANK_USD_ALIAS: str = 'OBYRA.APP'
    BANK_USD_ACCOUNT: str = '4008448-4 104-5'

    # Cuenta en PESOS (ARS)
    BANK_ARS_CBU: str = '0070104030004163653728'
    BANK_ARS_ALIAS: str = 'OBYRA.APP.PESOS'
    BANK_ARS_ACCOUNT: str = '4163653-7 104-2'

    # Legacy (mantener por compatibilidad)
    BANK_CBU: str = os.getenv('BILLING_BANK_CBU', '0070104031004008448459')
    BANK_ALIAS: str = os.getenv('BILLING_BANK_ALIAS', 'OBYRA.APP')

    # ============================================
    # MÉTODOS DE UTILIDAD
    # ============================================

    @classmethod
    def is_configured(cls) -> bool:
        """
        Verifica si la configuración de facturación está completa

        Returns:
            True si todos los datos obligatorios están configurados
        """
        required_fields = [
            cls.COMPANY_TAX_ID,
            cls.COMPANY_ADDRESS,
            cls.COMPANY_CITY,
            cls.COMPANY_PROVINCE,
        ]
        return all(field.strip() for field in required_fields)

    @classmethod
    def get_full_address(cls) -> str:
        """Retorna la dirección fiscal completa"""
        parts = [
            cls.COMPANY_ADDRESS,
            cls.COMPANY_CITY,
            cls.COMPANY_PROVINCE,
            cls.COMPANY_POSTAL_CODE
        ]
        return ', '.join(part for part in parts if part.strip())

    @classmethod
    def get_company_info(cls) -> dict:
        """
        Retorna toda la información de la empresa para usar en plantillas

        Returns:
            Diccionario con todos los datos de la empresa
        """
        return {
            'name': cls.COMPANY_NAME,
            'tax_id': cls.COMPANY_TAX_ID,
            'tax_condition': cls.COMPANY_TAX_CONDITION,
            'address': cls.COMPANY_ADDRESS,
            'city': cls.COMPANY_CITY,
            'province': cls.COMPANY_PROVINCE,
            'postal_code': cls.COMPANY_POSTAL_CODE,
            'full_address': cls.get_full_address(),
            'email': cls.COMPANY_EMAIL,
            'phone': cls.COMPANY_PHONE,
            'start_date': cls.COMPANY_START_DATE,
            'afip_pos': cls.AFIP_POS,
            'logo_path': cls.COMPANY_LOGO_PATH,
        }

    @classmethod
    def calculate_total_with_iva(cls, subtotal: float) -> tuple[float, float, float]:
        """
        Calcula el total con IVA

        Args:
            subtotal: Monto sin IVA

        Returns:
            Tupla con (subtotal, iva_monto, total)
        """
        iva_monto = subtotal * (cls.IVA_PERCENTAGE / 100)
        total = subtotal + iva_monto
        return (subtotal, iva_monto, total)

    @classmethod
    def get_bank_info(cls) -> dict:
        """
        Retorna información completa de cuentas bancarias para transferencias

        Returns:
            Diccionario con datos de cuentas USD y ARS
        """
        return {
            'enabled': cls.BANK_TRANSFER_ENABLED,
            'holder_name': cls.BANK_HOLDER_NAME,
            'holder_dni': cls.BANK_HOLDER_DNI,
            'bank_name': cls.BANK_NAME,
            'usd': {
                'cbu': cls.BANK_USD_CBU,
                'alias': cls.BANK_USD_ALIAS,
                'account': cls.BANK_USD_ACCOUNT,
            },
            'ars': {
                'cbu': cls.BANK_ARS_CBU,
                'alias': cls.BANK_ARS_ALIAS,
                'account': cls.BANK_ARS_ACCOUNT,
            }
        }


# Configuración global para fácil acceso
BILLING = BillingConfig
