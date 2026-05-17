from dataclasses import dataclass


@dataclass
class RenderJobMessage:
    job_id: str
    org_id: str
    input_spec: dict


def sqs_to_render_job(message) -> RenderJobMessage:
    """Parse SQS message body into RenderJobMessage.

    message.body is a dict with keys: job_id, org_id, input_spec.
    """
    body = message.body
    return RenderJobMessage(
        job_id=body["job_id"],
        org_id=body["org_id"],
        input_spec=body["input_spec"],
    )
