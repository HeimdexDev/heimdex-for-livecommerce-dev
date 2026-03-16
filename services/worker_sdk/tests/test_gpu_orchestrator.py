from unittest.mock import MagicMock, patch

import pytest
import requests

from heimdex_worker_sdk.aircloud_client import AircloudClient, EndpointStatus
from heimdex_worker_sdk.gpu_orchestrator import GPUOrchestrator, ensure_worker_running


def _mock_response(json_data=None, raise_error=None):
    resp = MagicMock()
    resp.json.return_value = json_data or {}
    if raise_error is None:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = raise_error
    return resp


def _build_aircloud_client():
    with patch("heimdex_worker_sdk.aircloud_client.requests.Session") as session_cls:
        session = MagicMock()
        session.headers = {}
        session_cls.return_value = session
        client = AircloudClient(api_key="test-key", base_url="https://aircloud.test", timeout=7)
    return client, session


def _build_orchestrator(
    wake_debounce_seconds=300,
    cooldown_checks=3,
    endpoint_map=None,
    queue_url_map=None,
):
    aircloud = MagicMock()
    orchestrator = GPUOrchestrator(
        aircloud_client=aircloud,
        endpoint_map=endpoint_map or {"transcode": "ep-trans", "caption": "ep-cap"},
        queue_url_map=queue_url_map
        or {
            "transcode": "https://sqs.aws/transcode",
            "caption": "https://sqs.aws/caption",
        },
        wake_debounce_seconds=wake_debounce_seconds,
        cooldown_checks=cooldown_checks,
    )
    return orchestrator, aircloud


def test_aircloud_get_status_returns_endpoint_status_on_success():
    client, session = _build_aircloud_client()
    session.get.return_value = _mock_response(
        {
            "endpoint_id": "ep-1",
            "name": "caption",
            "is_active": True,
            "num_replicas": 2,
            "replica_status_summary": {"RUNNING": 2},
            "enable_autoscaling": False,
            "instance_type_name": "A100",
        }
    )

    status = client.get_status("ep-1")

    assert isinstance(status, EndpointStatus)
    assert status.endpoint_id == "ep-1"
    assert status.is_active is True
    assert status.num_replicas == 2
    session.get.assert_called_once_with("https://aircloud.test/endpoints/ep-1", timeout=7)


def test_aircloud_get_status_returns_none_on_http_error():
    client, session = _build_aircloud_client()
    session.get.return_value = _mock_response(raise_error=requests.HTTPError("boom"))

    status = client.get_status("ep-1")

    assert status is None


def test_aircloud_get_status_returns_none_on_connection_error():
    client, session = _build_aircloud_client()
    session.get.side_effect = requests.ConnectionError("no route")

    status = client.get_status("ep-1")

    assert status is None


def test_aircloud_start_returns_true_on_success():
    client, session = _build_aircloud_client()
    session.post.return_value = _mock_response({"is_active": True, "message": "ok"})

    ok = client.start("ep-start")

    assert ok is True
    session.post.assert_called_once_with(
        "https://aircloud.test/endpoints/ep-start/start",
        timeout=7,
    )


def test_aircloud_start_returns_false_on_failure():
    client, session = _build_aircloud_client()
    session.post.side_effect = requests.Timeout("timeout")

    ok = client.start("ep-start")

    assert ok is False


def test_aircloud_stop_returns_true_on_success():
    client, session = _build_aircloud_client()
    session.post.return_value = _mock_response({"is_active": False, "message": "stopped"})

    ok = client.stop("ep-stop")

    assert ok is True
    session.post.assert_called_once_with(
        "https://aircloud.test/endpoints/ep-stop/stop",
        timeout=7,
    )


def test_aircloud_scale_returns_true_and_sends_correct_json_body():
    client, session = _build_aircloud_client()
    session.post.return_value = _mock_response(
        {
            "previous_replicas": 1,
            "current_replicas": 3,
            "message": "scaled",
        }
    )

    ok = client.scale("ep-scale", num_replicas=3)

    assert ok is True
    session.post.assert_called_once_with(
        "https://aircloud.test/endpoints/ep-scale/scale",
        json={"num_replicas": 3},
        timeout=7,
    )


def test_aircloud_authorization_header_is_set_correctly():
    _, session = _build_aircloud_client()

    assert session.headers["Authorization"] == "Bearer test-key"
    assert session.headers["Content-Type"] == "application/json"


def test_ensure_running_calls_aircloud_start_for_known_job_type():
    orchestrator, aircloud = _build_orchestrator()

    with patch("heimdex_worker_sdk.gpu_orchestrator.time.monotonic", return_value=1000.0):
        orchestrator.ensure_running("caption")

    aircloud.start.assert_called_once_with("ep-cap")


def test_ensure_running_is_noop_for_unknown_job_type():
    orchestrator, aircloud = _build_orchestrator()

    orchestrator.ensure_running("unknown")

    aircloud.start.assert_not_called()


def test_ensure_running_is_noop_when_endpoint_id_missing():
    orchestrator, aircloud = _build_orchestrator(endpoint_map={"transcode": ""})

    orchestrator.ensure_running("transcode")

    aircloud.start.assert_not_called()


def test_ensure_running_debounce_second_call_within_period_is_skipped():
    orchestrator, aircloud = _build_orchestrator(wake_debounce_seconds=300)

    with patch(
        "heimdex_worker_sdk.gpu_orchestrator.time.monotonic",
        side_effect=[1000.0, 1100.0],
    ):
        orchestrator.ensure_running("transcode")
        orchestrator.ensure_running("transcode")

    aircloud.start.assert_called_once_with("ep-trans")


def test_ensure_running_debounce_call_after_period_goes_through():
    orchestrator, aircloud = _build_orchestrator(wake_debounce_seconds=300)

    with patch(
        "heimdex_worker_sdk.gpu_orchestrator.time.monotonic",
        side_effect=[1000.0, 1301.0],
    ):
        orchestrator.ensure_running("transcode")
        orchestrator.ensure_running("transcode")

    assert aircloud.start.call_count == 2


def test_ensure_running_resets_cooldown_counter():
    orchestrator, _ = _build_orchestrator()
    orchestrator._empty_counts["caption"] = 2

    with patch("heimdex_worker_sdk.gpu_orchestrator.time.monotonic", return_value=1000.0):
        orchestrator.ensure_running("caption")

    assert orchestrator._empty_counts["caption"] == 0


def test_check_and_manage_stops_worker_after_consecutive_empty_checks():
    orchestrator, aircloud = _build_orchestrator(cooldown_checks=2)

    with patch.object(
        orchestrator,
        "_poll_all_queue_depths",
        return_value={"transcode": {"waiting": 0, "in_flight": 0}},
    ):
        orchestrator.check_and_manage()
        orchestrator.check_and_manage()

    aircloud.stop.assert_called_once_with("ep-trans")


def test_check_and_manage_does_not_stop_before_cooldown_threshold():
    orchestrator, aircloud = _build_orchestrator(cooldown_checks=3)

    with patch.object(
        orchestrator,
        "_poll_all_queue_depths",
        return_value={"transcode": {"waiting": 0, "in_flight": 0}},
    ):
        orchestrator.check_and_manage()

    aircloud.stop.assert_not_called()
    assert orchestrator._empty_counts["transcode"] == 1


def test_check_and_manage_resets_counter_when_queue_has_messages():
    orchestrator, aircloud = _build_orchestrator()
    orchestrator._empty_counts["transcode"] = 2

    with patch.object(
        orchestrator,
        "_poll_all_queue_depths",
        return_value={"transcode": {"waiting": 1, "in_flight": 1}},
    ):
        orchestrator.check_and_manage()

    assert orchestrator._empty_counts["transcode"] == 0
    aircloud.stop.assert_not_called()


def test_check_and_manage_skips_worker_when_queue_query_fails():
    orchestrator, aircloud = _build_orchestrator()
    orchestrator._empty_counts["transcode"] = 1

    with patch.object(orchestrator, "_poll_all_queue_depths", return_value={}):
        orchestrator.check_and_manage()

    aircloud.stop.assert_not_called()
    assert orchestrator._empty_counts["transcode"] == 1


def test_processing_job_type_maps_to_transcode_worker():
    orchestrator, aircloud = _build_orchestrator()

    with patch("heimdex_worker_sdk.gpu_orchestrator.time.monotonic", return_value=1000.0):
        orchestrator.ensure_running("processing")

    aircloud.start.assert_called_once_with("ep-trans")


def test_resplit_job_type_maps_to_transcode_worker():
    orchestrator, aircloud = _build_orchestrator()

    with patch("heimdex_worker_sdk.gpu_orchestrator.time.monotonic", return_value=1000.0):
        orchestrator.ensure_running("resplit")

    aircloud.start.assert_called_once_with("ep-trans")


def test_poll_all_queue_depths_uses_boto3_client_and_parses_counts():
    orchestrator, _ = _build_orchestrator(queue_url_map={"transcode": "https://sqs.aws/transcode"})
    sqs_client = MagicMock()
    sqs_client.get_queue_attributes.return_value = {
        "Attributes": {
            "ApproximateNumberOfMessages": "4",
            "ApproximateNumberOfMessagesNotVisible": "2",
        }
    }

    with patch("heimdex_worker_sdk.gpu_orchestrator.boto3.client", return_value=sqs_client) as boto_client:
        depths = orchestrator._poll_all_queue_depths()

    boto_client.assert_called_once_with("sqs", region_name="ap-northeast-2")
    assert depths == {"transcode": {"waiting": 4, "in_flight": 2}}


def test_poll_all_queue_depths_skips_queue_when_attribute_query_raises():
    orchestrator, _ = _build_orchestrator(
        queue_url_map={
            "transcode": "https://sqs.aws/transcode",
            "caption": "https://sqs.aws/caption",
        }
    )
    sqs_client = MagicMock()
    sqs_client.get_queue_attributes.side_effect = [
        Exception("boom"),
        {
            "Attributes": {
                "ApproximateNumberOfMessages": "1",
                "ApproximateNumberOfMessagesNotVisible": "0",
            }
        },
    ]

    with patch("heimdex_worker_sdk.gpu_orchestrator.boto3.client", return_value=sqs_client):
        depths = orchestrator._poll_all_queue_depths()

    assert depths == {"caption": {"waiting": 1, "in_flight": 0}}


def test_module_level_ensure_worker_running_returns_silently_when_disabled():
    with patch("heimdex_worker_sdk.gpu_orchestrator.get_orchestrator", return_value=None) as get_orch:
        result = ensure_worker_running("transcode")

    assert result is None
    get_orch.assert_called_once_with()
