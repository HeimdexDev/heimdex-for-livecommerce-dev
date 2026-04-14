"""User-initiated PII blur subsystem.

A user calls ``POST /api/videos/{file_id}/blur`` with options, the API
creates a ``blur_jobs`` row, publishes an SQS message, and returns
immediately. The ``drive-blur-worker`` GPU service consumes the message,
runs face + OWLv2 detection via ``heimdex_media_pipelines.blur``, writes
the blurred MP4 and manifest to S3, and calls the internal result
endpoint to transition the job to ``done``/``failed``.

This module is deliberately orthogonal to the transcode → enrichment →
indexing pipeline. Nothing downstream reacts to blur completion.
"""
