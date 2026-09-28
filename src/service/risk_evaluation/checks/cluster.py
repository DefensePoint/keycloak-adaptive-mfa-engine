import pandas as pd

from src.core.config.environment import ALLOWED_CLUSTERING_PARAMS

from src.service.clustering import ClusteringService


def process_cluster_label(df_user: pd.DataFrame, current_event_dict: dict) -> str:
    """
    Classify the CURRENT login's fingerprint against the user's history.

    Args:
        df_user (pd.DataFrame): The user's historical login events.
        current_event_dict (dict): The login being evaluated now.

    Returns:
        str: 'TREND', 'RARE', or 'ANOMALOUS'.
    """
    return ClusteringService.get_cluster_label(
        df_user, current_event_dict, ALLOWED_CLUSTERING_PARAMS
    )
