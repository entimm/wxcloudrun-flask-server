import logging

from flask import jsonify, request
from werkzeug.exceptions import HTTPException


def register_error_handlers(app):
    """Make every error return JSON instead of Flask's default HTML page."""

    # Ensure the runtime has a configured handler so stack traces reach the
    # container logs (Cloud Hosting collects stdout/stderr).
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
    )

    logger = logging.getLogger('wxcloudrun.errors')

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        if isinstance(error, HTTPException):
            # Keep intentional 4xx/5xx aborts meaningful but still JSON encoded.
            logger.warning(
                'HTTP %s on %s %s: %s',
                error.code,
                request.method,
                request.path,
                error.description,
            )
            return jsonify({'detail': error.description or error.name}), error.code

        logger.exception('Unhandled exception on %s %s', request.method, request.path)
        # The full stack trace is in the logs; the client only needs the reason.
        return jsonify({'detail': f'{type(error).__name__}: {error}'}), 500
