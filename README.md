# Conversor MT → MX

Aplicación web para llevar cartolas bancarias a formatos estándar: convierte entre
**cartolas en Excel**, **SWIFT MT940** e **ISO 20022 camt.053.001.08**.

Pensada para quien tiene una cartola de su banco y necesita entregarla en un formato
estándar: se carga el archivo, se revisa lo que el sistema entendió y recién entonces
se descarga el resultado.

## La interfaz

- **Barra lateral** con los tres flujos de conversión y la referencia de formatos.
- **Tres pasos** — Origen → Revisión → Resultado — que se van revelando a medida que avanzas.
- **Vista previa del archivo generado** antes de descargarlo, con opción de copiarlo.
- **Cartolas de ejemplo** cargables en un clic, para probar sin tener un archivo a mano.
- **Resumen del parseo**: movimientos, abonos, cargos, período y saldo de cierre.
- **«Cómo se leyó tu archivo»**: qué columna se interpretó como qué, y qué valores tuvo
  que deducir el parser (la cartola no trae saldo de apertura, código de operación, etc.).
- **Verificación de cuadre**: comprueba que saldo inicial + movimientos = saldo final.
- **Aviso de límites del formato**: advierte si un detalle excede lo que admite el campo
  `:86:` de MT940 antes de que se recorte.
- Tema claro / oscuro / sistema, tabla de movimientos filtrable y diseño responsive.

> Herramienta independiente. Sin afiliación con Banco Santander ni con ninguna otra
> institución financiera.

## Características

### MT940 → camt.053 XML
- Parser MT940 personalizado (campos `:20:` `:21:` `:25:` `:28C:` `:60F/M:` `:61:` `:86:` `:62F/M:` `:64:`)
- Soporte de múltiples statements por archivo
- Sub-campos estructurados `?XX` (formato DTA alemán)
- Archivos con CRLF, BOM UTF-8 y codificación Latin-1
- Generador XML con namespace `urn:iso:std:iso:20022:tech:xsd:camt.053.001.08`

### camt.053 XML → MT940
- Parser XML compatible con versiones `.001.02` a `.001.11`
- Generador MT940 con formato SWIFT (montos con coma decimal, fechas YYMMDD)
- Soporte IBAN, BIC, indicadores de reversión RC/RD
- Narrativa desde `<Ustrd>` y `<AddtlNtryInf>`

### Excel (cartola) → MT940 / camt.053 XML
- Lee cartolas bancarias `.xlsx` y `.xls`
- Detección automática de la fila de cabecera y de las columnas por su nombre
- Soporta distintos formatos de bancos sin configuración:
  * moneda `MONTO` con signo (Banco Falabella)
  * columnas separadas cargo/abono (Banco Santander: "Monto cargo"/"Monto abono")
  * columnas "Cargos"/"Abonos" con metadatos de cuenta (Banco de Chile)
- Detecta número de cuenta y moneda (CLP) desde los metadatos
- Los saldos inicial/final se derivan de la suma neta de transacciones y se fechan
  con el primer y el último movimiento, de modo que el período del camt.053
  (`FrToDt`) corresponde al que cubre la cartola
- El resultado del parseo incluye `meta.field_map` (qué columna se leyó como qué)
  y `meta.assumptions` (qué valores se dedujeron), que la interfaz muestra al usuario

## Instalación

```bash
git clone https://github.com/migueljimenop/mt-to-mx-cl
cd mt-to-mx-cl
pip3 install -r requirements.txt
```

## Uso

```bash
python3 run.py
```

Abre el navegador en `http://localhost:5000`

> Si el puerto 5000 está ocupado (AirPlay en macOS):
> ```bash
> flask --app run:app run --port 5001
> ```

## API

| Endpoint | Método | Descripción |
|---|---|---|
| `/api/parse` | POST | MT940 → JSON (preview) |
| `/api/convert` | POST | MT940 → camt.053 XML (descarga) |
| `/api/parse-xml` | POST | camt.053 XML → JSON (preview) |
| `/api/convert-xml` | POST | camt.053 XML → MT940 .txt (descarga) |
| `/api/parse-excel` | POST | cartola Excel (.xlsx/.xls) → JSON (preview) |
| `/api/convert-excel` | POST | cartola Excel → MT940 o camt.053 XML (descarga) |

Todos los endpoints reciben `multipart/form-data` con campo `file`.
`/api/convert-excel` acepta además el campo `target` con valor `mt940` o `xml` (por defecto `xml`).

## Formatos soportados

**MT940:** `.txt` `.sta` `.mt940` `.mt9` `.swift`  
**XML:** `.xml` (camt.053.001.02 – camt.053.001.11)  
**Excel:** `.xlsx` `.xls` (cartola bancaria)

Tamaño máximo de subida: 5 MB, configurable con la variable de entorno `MAX_UPLOAD_MB`.

## Tests

```bash
pip3 install pytest
python3 -m pytest tests/ -v
# 115 tests
```

## Estructura del proyecto

```
mt-to-mx-cl/
├── app/
│   ├── parser/
│   │   ├── mt940_parser.py      # Parser SWIFT MT940
│   │   ├── camt053_parser.py    # Parser ISO 20022 camt.053
│   │   ├── excel_parser.py      # Parser de cartolas Excel (.xlsx/.xls)
│   │   └── models.py           # Modelos de datos
│   ├── converter/
│   │   ├── camt053_generator.py # Generador XML camt.053
│   │   └── mt940_generator.py  # Generador MT940
│   ├── routes.py               # API Flask
│   ├── templates/index.html    # Interfaz web
│   └── static/
│       ├── css/ · js/          # Estilos y lógica de la interfaz
│       └── samples/            # Cartolas y archivos de ejemplo (datos sintéticos)
├── tests/
│   ├── fixtures/               # Archivos MT940, XML y Excel de prueba
│   ├── test_parser.py
│   ├── test_generator.py
│   ├── test_inverse.py
│   ├── test_routes.py
│   └── test_excel.py
├── requirements.txt
└── run.py
```

## Tecnologías

- **Backend:** Python 3.9+ · Flask 3.x
- **XML:** lxml · xml.etree.ElementTree
- **Frontend:** HTML5 · CSS3 · JavaScript (vanilla)
