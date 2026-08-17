# MT940 ↔ camt.053 Converter

Aplicación web que convierte entre el formato de estados de cuenta bancarios **SWIFT MT940** y el estándar XML **ISO 20022 camt.053.001.08**, en ambas direcciones.

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

## Instalación

```bash
git clone https://github.com/migueljimenop/mt-to-mx-cl
cd mt-to-mx-cl
pip3 install flask lxml
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

Todos los endpoints reciben `multipart/form-data` con campo `file`.

## Formatos soportados

**MT940:** `.txt` `.sta` `.mt940` `.mt9` `.swift`  
**XML:** `.xml` (camt.053.001.02 – camt.053.001.11)

## Tests

```bash
pip3 install pytest
python3 -m pytest tests/ -v
# 81 tests
```

## Estructura del proyecto

```
mt-to-mx-cl/
├── app/
│   ├── parser/
│   │   ├── mt940_parser.py      # Parser SWIFT MT940
│   │   ├── camt053_parser.py    # Parser ISO 20022 camt.053
│   │   └── models.py           # Modelos de datos
│   ├── converter/
│   │   ├── camt053_generator.py # Generador XML camt.053
│   │   └── mt940_generator.py  # Generador MT940
│   ├── routes.py               # API Flask
│   ├── templates/index.html    # Interfaz web
│   └── static/                 # CSS y JS
├── tests/
│   ├── fixtures/               # Archivos MT940 y XML de prueba
│   ├── test_parser.py
│   ├── test_generator.py
│   ├── test_inverse.py
│   └── test_routes.py
├── requirements.txt
└── run.py
```

## Tecnologías

- **Backend:** Python 3.9+ · Flask 3.x
- **XML:** lxml · xml.etree.ElementTree
- **Frontend:** HTML5 · CSS3 · JavaScript (vanilla)
