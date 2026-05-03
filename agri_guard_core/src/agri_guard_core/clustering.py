from typing import List, Tuple, Dict, Any
import numpy as np
try:
    from sklearn.cluster import DBSCAN
except ImportError:
    DBSCAN = None

def cluster_detections(detections: List[Dict[str, float]], eps_meters: float = 0.5, min_samples: int = 1) -> List[Dict[str, Any]]:
    """
    Clusters geospatial detections using DBSCAN to merge duplicate sightings.
    
    Args:
        detections: List of dicts with 'lat', 'lon', 'class_id', 'confidence'.
        eps_meters: The maximum distance between two samples for one to be considered as in the neighborhood of the other.
        min_samples: The number of samples (or total weight) in a neighborhood for a point to be considered as a core point.
        
    Returns:
        List of clustered incidents: [{'lat': ..., 'lon': ..., 'count': ..., 'avg_conf': ...}, ...]
    """
    if not detections:
        return []
        
    if DBSCAN is None:
        raise ImportError("scikit-learn is not installed.")

    # Convert Lat/Lon to approximate meters for clustering (Flat Earth approximation for small area)
    # Or use haversine metric with DBSCAN.
    # For speed on small fields, converting to local metric frame (UTM or relative meters) is easier.
    # Let's use a simple relative projection based on the first point.
    
    ref_lat = detections[0]['lat']
    ref_lon = detections[0]['lon']
    R = 6378137
    
    coords_m = []
    for d in detections:
        d_lat = math.radians(d['lat'] - ref_lat)
        d_lon = math.radians(d['lon'] - ref_lon)
        y = d_lat * R
        x = d_lon * R * math.cos(math.radians(ref_lat))
        coords_m.append([x, y])
        
    X = np.array(coords_m)
    
    # Run DBSCAN
    db = DBSCAN(eps=eps_meters, min_samples=min_samples).fit(X)
    labels = db.labels_
    
    # Aggregate results
    clusters = {}
    for i, label in enumerate(labels):
        if label == -1:
            # Noise (shouldn't happen with min_samples=1)
            continue
            
        if label not in clusters:
            clusters[label] = {
                'lat_sum': 0.0,
                'lon_sum': 0.0,
                'conf_sum': 0.0,
                'count': 0,
                'class_id': detections[i]['class_id'] # Assume same class for cluster
            }
        
        clusters[label]['lat_sum'] += detections[i]['lat']
        clusters[label]['lon_sum'] += detections[i]['lon']
        clusters[label]['conf_sum'] += detections[i]['confidence']
        clusters[label]['count'] += 1
        
    results = []
    for label, data in clusters.items():
        results.append({
            'lat': data['lat_sum'] / data['count'],
            'lon': data['lon_sum'] / data['count'],
            'class_id': data['class_id'],
            'count': data['count'],
            'avg_conf': data['conf_sum'] / data['count']
        })
        
    return results

import math
from typing import Any
