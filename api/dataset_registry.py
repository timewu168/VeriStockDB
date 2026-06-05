from __future__ import annotations

from dataclasses import dataclass

import config


@dataclass(frozen=True)
class DatasetDefinition:
    dataset: str
    title: str
    period_type: str
    markets: tuple[str, ...]
    status_endpoint: str


SUPPORTED_DATASETS = {
    config.DATASET_DAILY_CLOSE: DatasetDefinition(
        dataset=config.DATASET_DAILY_CLOSE,
        title="Daily Close",
        period_type="date",
        markets=config.MARKETS,
        status_endpoint=f"/api/v1/datasets/{config.DATASET_DAILY_CLOSE}/status",
    ),
    config.DATASET_ATTENTION_NOTICE: DatasetDefinition(
        dataset=config.DATASET_ATTENTION_NOTICE,
        title="Attention Notices",
        period_type="date_range",
        markets=config.MARKETS,
        status_endpoint=f"/api/v1/datasets/{config.DATASET_ATTENTION_NOTICE}/status",
    )
}


def list_datasets() -> list[DatasetDefinition]:
    return list(SUPPORTED_DATASETS.values())


def get_dataset_definition(dataset: str) -> DatasetDefinition | None:
    return SUPPORTED_DATASETS.get(dataset)
