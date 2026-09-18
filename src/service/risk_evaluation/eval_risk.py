import pandas as pd
from datetime import datetime
import pytz

from src.service.risk_evaluation.checks import (
    process_inactive_account,
    process_impossible_travel,
    process_time_interval,
    process_anonymous_detection,
    process_cluster_label,
    process_datetime_data,
    process_geo_cluster_label,
)
from src.service.risk_evaluation.checks.inactive_account import (
    resolve_inactive_threshold,
)
from src.core.config.environment import TIME_ZONE
import logging


class EvalRisk:
    """
    Class responsible for generating a risk evaluation fingerprint (risk_eval_vars)
    based on user authentication history and various behavioral checks.

    This class performs feature engineering on login history and returns a
    dictionary containing key risk indicators that will be consumed by
    downstream decision engines.
    """

    df_user: pd.DataFrame

    def __init__(
        self,
        df_user: pd.DataFrame,
        last_decision: int,
        second_last_decision: int,
        previous_event_dict: dict,
        current_event_dict: dict,
        enabled_params: list[str],
        inactive_days: int | None = None,
    ) -> None:
        """
        Initializes the EvalRisk class.

        Args:
            df_user (pd.DataFrame):
                DataFrame containing historical authentication events for the user.
            last_decision (int):
                The last decision level (e.g., risk level 1-4) from previous evaluation.
            second_last_decision (int):
                The second-to-last decision level.
            previous_event_dict (dict):
                Dictionary representing the previous authentication event's parameters.
            current_event_dict (dict):
                Dictionary representing the current authentication event's parameters.
            enabled_params (list[str]):
                List of parameters that are active/enabled for evaluation based on policy.
            inactive_days (int | None):
                Realm-configured dormancy threshold in days, or None to use the
                deployment default.
        """
        self.df_user = df_user
        self.last_decision = last_decision
        self.second_last_decision = second_last_decision
        self.previous_event_dict = previous_event_dict
        self.current_event_dict = current_event_dict
        self.enabled_params = enabled_params
        # Raw configured value; resolved at use so a None from an older config
        # (or from a caller that does not care) still gets the env default.
        self.inactive_days = inactive_days

    def process(self) -> dict:
        """
        Processes the input DataFrame and user context to generate a risk evaluation fingerprint.

        The method evaluates several key risk features like geolocation clustering,
        time interval anomalies, impossible travel, and others based on the
        user's login history and the currently enabled security parameters.

        Returns:
            dict:
                A dictionary containing evaluated risk parameters and metadata
                (like last and second-last decisions, previous/current events).
        """
        geocluster_label = "TREND"
        date_time = "LOW"
        anonymous_detection = "NOT ANONYMOUS"
        cluster_label = "TREND"
        time_interval = "ACCEPTABLE"
        impossible_travel = "POSSIBLE"
        inactive_account = "ACTIVE"

        weekday = datetime.now(pytz.timezone(TIME_ZONE)).strftime("%a")
        logging.debug("Current weekday identified as: %s", weekday)

        if "geolocation_cluster_label" in self.enabled_params:
            geocluster_label = process_geo_cluster_label(
                self.df_user, self.current_event_dict
            )
            logging.debug("Geolocation cluster label: %s", geocluster_label)

        if "date_time" in self.enabled_params:
            date_time = process_datetime_data(self.df_user, self.current_event_dict)
            logging.debug("Date/time risk assessment: %s", date_time)

        if "anonymous_detection" in self.enabled_params:
            anonymous_detection = process_anonymous_detection(
                self.df_user, self.current_event_dict
            )
            logging.debug("Anonymous detection status: %s", anonymous_detection)

        if "event_cluster_label" in self.enabled_params:
            cluster_label = process_cluster_label(
                self.df_user, self.current_event_dict
            )
            logging.debug("Event cluster label: %s", cluster_label)

        if "time_interval" in self.enabled_params:
            time_interval = process_time_interval(self.df_user)
            logging.debug("Time interval risk status: %s", time_interval)

        if "impossible_travel" in self.enabled_params:
            impossible_travel = process_impossible_travel(
                self.df_user, self.current_event_dict
            )
            logging.debug("Impossible travel status: %s", impossible_travel)

        if "inactive_account" in self.enabled_params:
            threshold_days = resolve_inactive_threshold(self.inactive_days)
            inactive_account = process_inactive_account(
                self.df_user, self.current_event_dict, threshold_days
            )
            logging.debug(
                "Inactive account status: %s (threshold %d days)",
                inactive_account,
                threshold_days,
            )

        risk_eval_vars = {
            "impossible_travel": impossible_travel,
            "anonymous_detection": anonymous_detection,
            "weekday": weekday,
            "date_time": date_time,
            "time_interval": time_interval,
            "inactive_account": inactive_account,
            "event_cluster_label": cluster_label,
            "geolocation_cluster_label": geocluster_label,
            "previous_event": self.previous_event_dict,
            "current_event": self.current_event_dict,
            "second_last_decision": self.second_last_decision,
            "last_decision": self.last_decision,
            # "location_consistency": location_consistency,  # Reserved for future use
        }

        logging.info("Generated risk_eval_vars: %s", risk_eval_vars)
        return risk_eval_vars
