from flask import Blueprint, jsonify, render_template, request, Response

from .converter import Camt053Generator, MT940Generator
from .parser import Camt053Parser, MT940Parser

bp = Blueprint('main', __name__)

_mt940_parser   = MT940Parser()
_camt053_parser = Camt053Parser()
_camt053_gen    = Camt053Generator()
_mt940_gen      = MT940Generator()

MT940_EXTENSIONS = {'txt', 'sta', 'mt940', 'mt9', 'swift'}
XML_EXTENSIONS   = {'xml', 'xsd'}


def _read_upload(allowed_exts: set) -> tuple:
    """
    Read and decode the uploaded file.
    Returns (text, filename, error_response_or_None).
    """
    if 'file' not in request.files:
        return None, None, (jsonify({'error': 'No se proporcionó ningún archivo.'}), 400)

    file = request.files['file']
    if file.filename == '':
        return None, None, (jsonify({'error': 'No se seleccionó ningún archivo.'}), 400)

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed_exts:
        return None, None, (
            jsonify({'error': f'Tipo de archivo no permitido. Esperado: {", ".join(sorted(allowed_exts))}'}),
            400,
        )

    try:
        raw_bytes = file.read()
        try:
            text = raw_bytes.decode('utf-8')
        except UnicodeDecodeError:
            text = raw_bytes.decode('latin-1')
    except Exception as exc:
        return None, None, (jsonify({'error': f'No se pudo leer el archivo: {exc}'}), 400)

    return text, file.filename, None


def _build_download(content: str, filename: str, mimetype: str) -> Response:
    return Response(
        content,
        mimetype=mimetype,
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': f'{mimetype}; charset=UTF-8',
        },
    )


# ---------------------------------------------------------------------------
# Common routes
# ---------------------------------------------------------------------------

@bp.route('/')
def index():
    return render_template('index.html')


# ---------------------------------------------------------------------------
# MT940 → camt.053 routes
# ---------------------------------------------------------------------------

@bp.route('/api/parse', methods=['POST'])
def api_parse():
    """Parse MT940 → JSON preview."""
    text, filename, err = _read_upload(MT940_EXTENSIONS)
    if err:
        return err

    result = _mt940_parser.parse(text, filename)
    return jsonify(result.to_dict())


@bp.route('/api/convert', methods=['POST'])
def api_convert():
    """Convert MT940 → camt.053 XML download."""
    text, filename, err = _read_upload(MT940_EXTENSIONS)
    if err:
        return err

    result = _mt940_parser.parse(text, filename)
    if result.errors and not result.statements:
        return jsonify({
            'error': 'El parseo MT940 falló — no se encontraron statements válidos.',
            'details': result.errors,
        }), 422

    xml_output = _camt053_gen.generate(result)
    base = filename.rsplit('.', 1)[0] if '.' in filename else filename
    return _build_download(xml_output, f'{base}_camt053.xml', 'application/xml')


# ---------------------------------------------------------------------------
# camt.053 → MT940 (inverse) routes
# ---------------------------------------------------------------------------

@bp.route('/api/parse-xml', methods=['POST'])
def api_parse_xml():
    """Parse camt.053 XML → JSON preview."""
    text, filename, err = _read_upload(XML_EXTENSIONS)
    if err:
        return err

    result = _camt053_parser.parse(text, filename)
    return jsonify(result.to_dict())


@bp.route('/api/convert-xml', methods=['POST'])
def api_convert_xml():
    """Convert camt.053 XML → MT940 text download."""
    text, filename, err = _read_upload(XML_EXTENSIONS)
    if err:
        return err

    result = _camt053_parser.parse(text, filename)
    if result.errors and not result.statements:
        return jsonify({
            'error': 'El parseo camt.053 falló — no se encontraron statements válidos.',
            'details': result.errors,
        }), 422

    mt940_output = _mt940_gen.generate(result)
    base = filename.rsplit('.', 1)[0] if '.' in filename else filename
    return _build_download(mt940_output, f'{base}_mt940.txt', 'text/plain')
