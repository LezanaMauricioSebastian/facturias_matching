# Snapshot proceso 89 (antes de pie-only)

- Capturado: 2026-08-07
- Staging: `https://odoo-dev-5weh2lz2hq-rj.a.run.app/?proceso=89`
- Full JSON: `proceso-89-before-pie-only.json`
- source=saved saved_at=2026-08-07 00:34:46 profile=default

## Factura (conversión guardada)

| Campo | Valor |
|-------|-------|
| Doc | 00008-00077777 |
| Proveedor | MERITI SRL |
| CUIT | 30708395796 |
| Precio | 272.644,68 |
| Qty | 1 |
| Etiqueta | Factura por los consumos correspondiente al periodo 2026-4 según mail de detalle |

## IVA

| Campo | Valor |
|-------|-------|
| Impuesto IVA | 21 |
| iva_monto (línea) | 57.255,38 |
| __fac_iva_monto | 57255.38 |
| __fac_iva_montos | {"21":"57255.38"} |

## Otros impuestos (slots + FacturIA)

```json
{
  "__fac_percepciones": [
    {
      "amount_key": "percepcion_iibb",
      "monto": "3544.38",
      "ui_monto_key": "otros_impuestos_monto"
    }
  ],
  "otros_impuestos": "Percepción Ganancias Sufrida",
  "otros_impuestos_3": "IVA Adicional 20%",
  "otros_impuestos_3_monto": "3,00",
  "otros_impuestos_4": "Perc. Municipal Corrientes",
  "otros_impuestos_4_monto": "4,00",
  "otros_impuestos_5": "Percepción IIBB Formosa Sufrida",
  "otros_impuestos_5_monto": "77,00",
  "otros_impuestos_6": "IVA 2,5%",
  "otros_impuestos_6_monto": "2,00",
  "otros_impuestos_monto": "6,00"
}
```

## FacturIA original (MySQL staging MERITI.pdf)

| Campo | Valor |
|-------|-------|
| numero_factura | 0008-00049267 |
| subtotal_sin_iva | 272644.68 |
| alicuota_iva | 21 |
| iva_21 | **57255.38** |
| percepcion_iibb | **3544.38** |
| total | 333444.44 |
