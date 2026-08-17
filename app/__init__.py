import os

from flask import Flask


def create_app(config: dict | None = None):
    """Create and configure the Flask application.

    Settings are read from environment variables and can be overridden
    per-instance via ``config``.
    """
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = int(
        os.environ.get('MAX_UPLOAD_MB', '5')
    ) * 1024 * 1024  # Max upload size (MB), configurable via env

    if config:
        app.config.update(config)

    from .routes import bp
    app.register_blueprint(bp)

    return app
