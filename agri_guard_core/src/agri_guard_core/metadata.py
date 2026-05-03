import os
from typing import Dict, Optional, Any
from PIL.ExifTags import TAGS

from agri_guard_core.pil_open import open_image

class MetadataError(Exception):
    pass



def _get_if_exist(data, key):
    if key in data:
        return data[key]
    return None

def _convert_to_degrees(value):
    """
    Helper function to convert the GPS coordinates stored in the EXIF to degress in float format
    """
    d = float(value[0])
    m = float(value[1])
    s = float(value[2])
    return d + (m / 60.0) + (s / 3600.0)

def extract_exif(image_path: str) -> Dict[str, Any]:
    """
    Extracts basic EXIF data (Dimensions, Focal Length, GPS) from an image.
    """
    meta = {}
    try:
        # Unpatched PIL open (see `pil_open.py`); avoids Ultralytics HEIF branch for DJI JPEG.
        with open_image(image_path) as img:
            exif_data = img._getexif()
            if exif_data:
                for tag, value in exif_data.items():
                    decoded = TAGS.get(tag, tag)
                    if decoded == 'ExifImageWidth': meta['width'] = value
                    if decoded == 'ExifImageHeight': meta['height'] = value
                    if decoded == 'FocalLength': meta['focal_length_mm'] = float(value)
                    if decoded == 'Make': meta['make'] = value
                    if decoded == 'Model': meta['model'] = value
                    if decoded == 'GPSInfo':
                        gps_info = value

                        gps_latitude = _get_if_exist(gps_info, 2)
                        gps_latitude_ref = _get_if_exist(gps_info, 1)
                        gps_longitude = _get_if_exist(gps_info, 4)
                        gps_longitude_ref = _get_if_exist(gps_info, 3)

                        if gps_latitude and gps_latitude_ref and gps_longitude and gps_longitude_ref:
                            lat = _convert_to_degrees(gps_latitude)
                            if gps_latitude_ref != 'N':
                                lat = -lat

                            lon = _convert_to_degrees(gps_longitude)
                            if gps_longitude_ref != 'E':
                                lon = -lon

                            meta['lat'] = lat
                            meta['lon'] = lon

    except Exception as e:
        raise MetadataError(f"Failed to read EXIF from {image_path}: {e}")

    return meta

def extract_xmp(image_path: str) -> Dict[str, float]:
    """
    Extracts DJI-specific XMP data (Gimbal, Altitude) by raw string parsing.
    """
    meta = {}
    try:
        with open(image_path, 'rb') as f:
            content = f.read()
            xmp_start = content.find(b'<x:xmpmeta')
            xmp_end = content.find(b'</x:xmpmeta>')
            
            if xmp_start != -1 and xmp_end != -1:
                xmp_str = content[xmp_start:xmp_end+12].decode('utf-8', errors='ignore')
                for line in xmp_str.split('\n'):
                    if 'drone-dji:RelativeAltitude' in line:
                        meta['rel_alt'] = float(line.split('"')[1])
                    if 'drone-dji:GimbalYawDegree' in line:
                        meta['gimbal_yaw'] = float(line.split('"')[1])
                    if 'drone-dji:GimbalPitchDegree' in line:
                        meta['gimbal_pitch'] = float(line.split('"')[1])
                    if 'drone-dji:GimbalRollDegree' in line:
                        meta['gimbal_roll'] = float(line.split('"')[1])
    except Exception as e:
        raise MetadataError(f"Failed to read XMP from {image_path}: {e}")
        
    return meta

def extract_mrk(mrk_path: str, image_index: int) -> Dict[str, float]:
    """
    Extracts high-precision GPS from a .MRK file for a specific image index.
    Image index is typically 1-based (e.g., 0001.JPG -> 1).
    """
    meta = {}
    try:
        with open(mrk_path, 'r') as f:
            lines = f.readlines()
            if image_index <= len(lines):
                # MRK format: Index, Time, ..., Lat, Lon, Ellh, ...
                # Example: 1	375756.996314	... 35.47579405,Lat	119.57562933,Lon ...
                line = lines[image_index - 1]
                parts = line.split('\t')
                for part in parts:
                    if ',Lat' in part:
                        meta['lat'] = float(part.split(',')[0])
                    if ',Lon' in part:
                        meta['lon'] = float(part.split(',')[0])
                    if ',Ellh' in part:
                        meta['ellh'] = float(part.split(',')[0])
            else:
                raise MetadataError(f"Image index {image_index} out of range in MRK file")
    except Exception as e:
        raise MetadataError(f"Failed to read MRK from {mrk_path}: {e}")
        
    return meta

def get_image_metadata(image_path: str, mrk_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Aggregates all metadata for an image.
    """
    # 1. EXIF
    meta = extract_exif(image_path)
    
    # 2. XMP
    meta.update(extract_xmp(image_path))
    
    # 3. MRK (if available)
    if mrk_path:
        # Infer index from filename: DJI_..._0001.JPG -> 1
        try:
            basename = os.path.basename(image_path)
            idx_str = basename.split('_')[-1].split('.')[0]
            idx = int(idx_str)
            meta.update(extract_mrk(mrk_path, idx))
        except ValueError:
            print(f"Warning: Could not infer index from filename {image_path}, skipping MRK.")
    
    # Sensor Defaults (Zenmuse P1)
    # TODO: Move to a config or lookup based on 'Model' tag
    if meta.get('model') == 'ZenmuseP1':
        meta['sensor_width_mm'] = 35.9
        meta['sensor_height_mm'] = 24.0
    else:
        # Fallback or error
        meta['sensor_width_mm'] = 35.9
        meta['sensor_height_mm'] = 24.0
        
    return meta
