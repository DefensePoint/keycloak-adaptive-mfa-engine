import numpy as np
import pandas as pd
from collections import Counter
from kmodes.kmodes import KModes
from sklearn.cluster import DBSCAN

import logging

from src.core.config.environment import GEOLOC_RADIUS


class ClusteringService:

    @staticmethod
    def __kModes_clusters(df, K):
        # init="Cao" is deterministic, so n_init>1 is wasted; verbose=1 spams logs.
        kmode = KModes(n_clusters=K, init="Cao", n_init=1, verbose=0)
        clusters = kmode.fit_predict(df)

        return clusters

    @staticmethod
    def __dbscan_clustering(latitudes, longitudes, epsilon=1, min_samples=2):

        kms_per_radian = 6371.0088
        epsilon /= kms_per_radian

        dbscan = DBSCAN(
            eps=epsilon,
            min_samples=min_samples,
            algorithm="ball_tree",
            metric="haversine",
        )

        dbscan.fit(np.radians([x for x in zip(latitudes, longitudes)]))

        return pd.Series(dbscan.labels_, name="geolocation_cluster_label")

    @staticmethod
    def __classify_by_membership(labels) -> str:
        """Classify the CURRENT login (the last row) by how common its cluster is.

        - alone (no historical login shares its cluster) -> ANOMALOUS
        - in the user's largest/most-common cluster        -> TREND
        - in a smaller-but-shared cluster                  -> RARE
        """
        labels = list(labels)
        current = labels[-1]
        counts = Counter(labels)

        if counts[current] <= 1:
            return "ANOMALOUS"
        if counts[current] == max(counts.values()):
            return "TREND"
        return "RARE"

    @staticmethod
    def get_cluster_label(
        df_user: pd.DataFrame, current_event: dict, enabled_feature_dict
    ) -> str:
        """Classify the current login's fingerprint relative to the user's history.

        The current login is appended as the final row and clustered together with
        the history, so the decision is made about the login being evaluated now
        (not an old stored event). Risk comes from cluster membership, not from the
        clustering library's arbitrary cluster numbering.

        Defensive: clusters only on features that exist both in the history and in
        the current event, so a partial fingerprint cannot crash the check. With no
        usable feature it returns TREND (cannot assess -> benign).
        """
        if df_user is None or df_user.empty:
            return "TREND"

        clustering_features = [
            k
            for k in enabled_feature_dict
            if k in df_user.columns and current_event.get(k) is not None
        ]
        if not clustering_features:
            return "TREND"

        # Categorical clustering: coerce to string and fill gaps so missing values
        # are a consistent category rather than a crash (None vs str comparison).
        history = df_user[clustering_features].fillna("").astype(str)
        current_row = pd.DataFrame(
            [{f: str(current_event[f]) for f in clustering_features}]
        )
        combined = pd.concat([history, current_row], ignore_index=True)

        nunique = combined.nunique()
        K = 3 if np.any(nunique >= 3) else (2 if nunique.max() == 2 else 1)
        logging.debug("Event clustering: K=%s, n=%s", K, len(combined))

        cluster_labels = ClusteringService.__kModes_clusters(combined.values, K)
        return ClusteringService.__classify_by_membership(cluster_labels)

    @staticmethod
    def get_geo_cluster_label(df_user: pd.DataFrame, current_event: dict) -> str:
        """Classify the current login's location relative to the user's history.

        The current login's coordinates are appended as the final point. DBSCAN
        noise (a point far from any cluster) is ANOMALOUS; otherwise risk comes
        from how common the current login's location cluster is.

        Defensive: if the current login could not be geolocated (missing or (0,0)
        coordinates, as geocoding failures produce), location cannot be assessed
        and the result is TREND (benign) - mirroring the impossible_travel check.
        Invalid history coordinates (NaN / (0,0)) are dropped before clustering.
        """
        if df_user is None or df_user.empty:
            return "TREND"

        cur_lat = current_event.get("lat")
        cur_long = current_event.get("long")
        if cur_lat is None or cur_long is None:
            return "TREND"
        try:
            cur_lat = float(cur_lat)
            cur_long = float(cur_long)
        except (TypeError, ValueError):
            return "TREND"
        if cur_lat == 0.0 and cur_long == 0.0:
            return "TREND"

        hist = (
            df_user[["lat", "long"]]
            .apply(pd.to_numeric, errors="coerce")
            .dropna()
        )
        # Drop failed-geocode history rows so they don't distort clustering.
        hist = hist[~((hist["lat"] == 0.0) & (hist["long"] == 0.0))]
        if hist.empty:
            return "TREND"

        latitudes = list(hist["lat"].values) + [cur_lat]
        longitudes = list(hist["long"].values) + [cur_long]

        labels = list(
            ClusteringService.__dbscan_clustering(
                latitudes, longitudes, epsilon=GEOLOC_RADIUS
            ).values
        )
        current = labels[-1]

        if current == -1:
            return "ANOMALOUS"

        counts = Counter(labels)
        if counts[current] == max(counts.values()):
            return "TREND"
        return "RARE"
