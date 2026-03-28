from flask import Blueprint, jsonify, render_template, request, Response

from .converter import Camt053Generator
from .parser import MT940Parser

bp = Blueprint('main', __name__)

_parser = MT940Parser()
_generator = Camt053Generator()

ALLOWED_EXTENSIONS = {'txt', 'sta', 'mt940', 'mt9', 'swift'}


def _allowed(filename: str) -> bool:
    return '.' not in filename or filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _read_upload() -> tuple:
    """Read and decode the uploaded file. Returns (text, filename, error_response)."""
    if 'file' not in request.files:
        return None, None, (jsonify({'error': 'No file provided.'}), 400)

    file = request.files['file']
    if file.filename == '':
        return None, None, (jsonify({'error': 'No file selected.'}), 400)

    if not _allowed(file.filename):
        return None, None, (
            jsonify({'error': f'File type not allowed. Expected: {", ".join(ALLOWED_EXTENSIONS)}'}),
            400,
        )

    try:
        raw_bytes = file.read()
        # Try UTF-8 first, then latin-1 as fallback (common in older SWIFT files)
        try:
            text = raw_bytes.decode('utf-8')
        except UnicodeDecodeError:
            text = raw_bytes.decode('latin-1')
    except Exception as exc:
        return None, None, (jsonify({'error': f'Could not read file: {exc}'}), 400)

    return text, file.filename, None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route('/')
def index():
    return render_template('index.html')


@bp.route('/api/parse', methods=['POST'])
def api_parse():
    """
    Parse an MT940 file and return structured JSON for preview.

    Request: multipart/form-data with field 'file'
    Response: JSON with statements array
    """
    text, filename, err = _read_upload()
    if err:
        return err

    result = _parser.parse(text, filename)
    return jsonify(result.to_dict())


@bp.route('/api/convert', methods=['POST'])
def api_convert():
    """
    Convert an MT940 file to camt.053 XML and return as a download.

    Request: multipart/form-data with field 'file'
    Response: XML file download
    """
    text, filename, err = _read_upload()
    if err:
        return err

    result = _parser.parse(text, filename)

    if result.errors and not result.statements:
        return jsonify({
            'error': 'MT940 parsing failed — no valid statements found.',
            'details': result.errors,
        }), 422

    xml_output = _generator.generate(result)

    # Build download filename
    base = filename.rsplit('.', 1)[0] if '.' in filename else filename
    download_name = f'{base}_camt053.xml'

    return Response(
        xml_output,
        mimetype='application/xml',
        headers={
            'Content-Disposition': f'attachment; filename="{download_name}"',
            'Content-Type': 'application/xml; charset=UTF-8',
        },
    )
