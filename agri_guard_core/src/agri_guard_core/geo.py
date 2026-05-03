import math
from typing import Dict, Tuple

def project_pixel_to_gps(meta: Dict[str, float], pixel_x: float, pixel_y: float) -> Tuple[float, float]:
    """
    Calculates the GPS coordinates (Lat, Lon) of a specific pixel in the image.
    
    Args:
        meta: Dictionary containing metadata (lat, lon, rel_alt, gimbal_yaw, width, height, focal_length_mm, sensor_width_mm, sensor_height_mm).
        pixel_x: X coordinate of the pixel (0 is left).
        pixel_y: Y coordinate of the pixel (0 is top).
        
    Returns:
        (Latitude, Longitude) of the pixel.
    """
    required_keys = ['lat', 'lon', 'rel_alt', 'gimbal_yaw', 'width', 'height', 'focal_length_mm', 'sensor_width_mm', 'sensor_height_mm']
    for key in required_keys:
        if key not in meta:
            raise ValueError(f"Missing required metadata key: {key}")

    # 1. Calculate Ground Sampling Distance (GSD) in meters/pixel
    # GSD = (Sensor Width / Image Width) * (Altitude / Focal Length)
    # We convert sensor width to meters (mm / 1000) first? No, keep mm ratio.
    # (mm / pixels) * (m / mm) -> m/pixel
    
    # Sensor resolution (mm/pixel)
    sensor_res_w = meta['sensor_width_mm'] / meta['width']
    sensor_res_h = meta['sensor_height_mm'] / meta['height']
    
    # GSD (m/pixel)
    gsd_w = sensor_res_w * (meta['rel_alt'] / meta['focal_length_mm'])
    gsd_h = sensor_res_h * (meta['rel_alt'] / meta['focal_length_mm'])
    
    # Use average GSD
    gsd = (gsd_w + gsd_h) / 2.0
    
    # 2. Calculate offset from image center in pixels
    center_x = meta['width'] / 2.0
    center_y = meta['height'] / 2.0
    
    # Image Frame: X right, Y down
    delta_px_x = pixel_x - center_x
    delta_px_y = pixel_y - center_y 
    
    # 3. Convert to physical distance in meters (Camera Frame)
    # Camera Frame: X right, Y down (relative to image center)
    dist_x_m = delta_px_x * gsd
    dist_y_m = delta_px_y * gsd
    
    # 4. Rotate based on Gimbal Yaw to align with North/East
    # DJI Yaw: 0 is North, 90 is East, -90 is West (Clockwise positive?)
    # Wait, DJI Yaw is usually: 0 North, +90 East, -90 West.
    # Let's align with standard map frame: North (Y), East (X).
    
    # Image Top (negative Y in image) points to the direction of the camera heading.
    # If Yaw=0 (North), Image Top points North.
    # So Image Y axis (down) points South.
    # Image X axis (right) points East.
    
    # Vector V_img = (dist_x_m, dist_y_m)
    # If Yaw=0:
    #   East_offset = dist_x_m
    #   North_offset = -dist_y_m (because dist_y_m is positive down/South)
    
    # If Yaw=90 (East):
    #   Image Top points East.
    #   Image Right points South.
    #   Image Down points West.
    #   East_offset = -dist_y_m
    #   North_offset = -dist_x_m
    
    # Let's use the rotation formula derived in prototype:
    # math_angle = 90 - yaw
    # offset_e = x * cos(a) - (-y) * sin(a) ... wait, let's stick to the verified prototype logic.
    
    # Prototype Logic:
    # local_x = dist_x_m
    # local_y = -dist_y_m (Up/Forward is positive)
    # math_angle_rad = math.radians(90 - meta['gimbal_yaw'])
    # offset_e = local_x * math.cos(math_angle_rad) - local_y * math.sin(math_angle_rad)
    # offset_n = local_x * math.sin(math_angle_rad) + local_y * math.cos(math_angle_rad)
    
    local_x = dist_x_m
    local_y = -dist_y_m
    
    math_angle_rad = math.radians(90 - meta['gimbal_yaw'])
    
    offset_e = local_x * math.cos(math_angle_rad) - local_y * math.sin(math_angle_rad)
    offset_n = local_x * math.sin(math_angle_rad) + local_y * math.cos(math_angle_rad)
    
    # 5. Convert Meters to Lat/Lon
    # Earth Radius ~ 6378137 m
    R = 6378137
    
    d_lat = offset_n / R
    d_lon = offset_e / (R * math.cos(math.radians(meta['lat'])))
    
    lat_rad = math.radians(meta['lat']) + d_lat
    lon_rad = math.radians(meta['lon']) + d_lon
    
    final_lat = math.degrees(lat_rad)
    final_lon = math.degrees(lon_rad)
    
    return final_lat, final_lon
