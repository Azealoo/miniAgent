"""Prometheus-scrapable metrics endpoint.

GET /api/metrics — returns the BioAPEX runtime counters / histograms in the
Prometheus text exposition format (``text/plain; version=0.0.4``). The
metric set is produced by :mod:`runtime.metrics_collector`, which is fed
from the chat turn hot-path in :mod:`runtime.query_engine`.
"""
from fastapi import APIRouter, Response

from runtime.metrics_collector import METRICS


PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

router = APIRouter()


@router.get("/metrics")
def metrics() -> Response:
    return Response(
        content=METRICS.render_exposition(),
        media_type=PROMETHEUS_CONTENT_TYPE,
    )
