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
    ),
    config.DATASET_DISPOSAL_NOTICE: DatasetDefinition(
        dataset=config.DATASET_DISPOSAL_NOTICE,
        title="Disposal Notices",
        period_type="date_range",
        markets=config.MARKETS,
        status_endpoint=f"/api/v1/datasets/{config.DATASET_DISPOSAL_NOTICE}/status",
    ),
    config.DATASET_LEGAL_INVESTOR: DatasetDefinition(
        dataset=config.DATASET_LEGAL_INVESTOR,
        title="Legal Investors",
        period_type="date",
        markets=config.MARKETS,
        status_endpoint=f"/api/v1/datasets/{config.DATASET_LEGAL_INVESTOR}/status",
    ),
    config.DATASET_MARGIN: DatasetDefinition(
        dataset=config.DATASET_MARGIN,
        title="Margin Trading",
        period_type="date",
        markets=config.MARKETS,
        status_endpoint=f"/api/v1/datasets/{config.DATASET_MARGIN}/status",
    ),
    config.DATASET_DAY_TRADING: DatasetDefinition(
        dataset=config.DATASET_DAY_TRADING,
        title="Day Trading",
        period_type="date",
        markets=config.MARKETS,
        status_endpoint=f"/api/v1/datasets/{config.DATASET_DAY_TRADING}/status",
    ),
    config.DATASET_REVENUE: DatasetDefinition(
        dataset=config.DATASET_REVENUE,
        title="Monthly Revenue",
        period_type="month",
        markets=config.MARKETS,
        status_endpoint=f"/api/v1/datasets/{config.DATASET_REVENUE}/status",
    ),
}


def list_datasets() -> list[DatasetDefinition]:
    return list(SUPPORTED_DATASETS.values())


def get_dataset_definition(dataset: str) -> DatasetDefinition | None:
    return SUPPORTED_DATASETS.get(dataset)
